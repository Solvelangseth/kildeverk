"""Look up words in Bokmålsordboka and Nynorskordboka."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from kildeverk.context import Context
from kildeverk.core.envelope import Provenance, Result
from kildeverk.core.operation import Operation
from kildeverk.sources.ordbokene.spec import ARTICLE_PAGE, BASE_URL, CREDIT, SPEC

DICTIONARIES = {"bm": "bokmål", "nn": "nynorsk"}
WORD_CLASSES = {
    "NOUN": "noun",
    "VERB": "verb",
    "ADJ": "adjective",
    "ADV": "adverb",
    "PRON": "pronoun",
    "ADP": "preposition",
    "CCONJ": "conjunction",
    "SCONJ": "subjunction",
    "INTJ": "interjection",
    "DET": "determiner",
    "NUM": "numeral",
    "PROPN": "proper noun",
    "EXPR": "expression",
}
GENDERS = {"Masc": "masculine", "Fem": "feminine", "Neuter": "neuter"}


class LookupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word: str = Field(
        min_length=1,
        max_length=60,
        description="The word, e.g. 'fjord'. '*' matches any letters ('spring*').",
    )
    dictionary: Literal["bm", "nn", "both"] = Field(
        default="both", description="'bm' for Bokmålsordboka, 'nn' for Nynorskordboka."
    )
    limit: int = Field(default=3, ge=1, le=10, description="Articles per dictionary.")


class Form(BaseModel):
    form: str
    tags: list[str] = Field(description="Grammar tags from the dictionary, e.g. ['Plur', 'Def'].")


class Meaning(BaseModel):
    text: str
    examples: list[str]


class Article(BaseModel):
    dictionary: Literal["bokmål", "nynorsk"]
    id: int
    words: list[str] = Field(description="The headword or headwords.")
    word_class: str | None
    gender: str | None
    forms: list[Form] = Field(description="The standard inflected forms.")
    meanings: list[Meaning]
    origin: str | None
    url: str


class LookupOutput(BaseModel):
    articles: list[Article]
    total_matches: dict[str, int] = Field(description="Articles found per dictionary.")
    did_you_mean: list[str] = Field(description="Similar words, when nothing matched.")
    credit: str = Field(description="The credit the dictionaries require wherever this is shown.")


def _render(block: dict[str, Any] | None, concepts: dict[str, Any]) -> str:
    """Fill the '$' placeholders in a text with its items, in order."""

    if not block:
        return ""
    content = block.get("content") or ""
    for item in block.get("items") or []:
        content = content.replace("$", _item(item, concepts), 1)
    return " ".join(content.split())


def _item(item: dict[str, Any], concepts: dict[str, Any]) -> str:
    if item.get("text"):
        return str(item["text"])
    if item.get("lemmas"):
        return str(item["lemmas"][0].get("lemma") or "")
    if item.get("type_") == "fraction":
        return f"{item.get('numerator')}/{item.get('denominator')}"
    concept = concepts.get(str(item.get("id"))) or {}
    return str(concept.get("expansion") or item.get("id") or "")


def _meanings(elements: list[dict[str, Any]], concepts: dict[str, Any]) -> list[Meaning]:
    out: list[Meaning] = []
    for element in elements:
        kind = element.get("type_")
        if kind == "definition":
            texts = [
                _render(e, concepts)
                for e in element.get("elements") or []
                if e.get("type_") == "explanation"
            ]
            examples = [
                _render(e.get("quote"), concepts)
                for e in element.get("elements") or []
                if e.get("type_") == "example"
            ]
            text = "; ".join(t for t in texts if t)
            if text or examples:
                out.append(Meaning(text=text, examples=[x for x in examples if x]))
            out.extend(_meanings(element.get("elements") or [], concepts))
    return out


def _article(dictionary: str, data: dict[str, Any], concepts: dict[str, Any]) -> Article:
    lemmas = data.get("lemmas") or []
    first = lemmas[0] if lemmas else {}
    paradigms = first.get("paradigm_info") or []
    current = next((p for p in paradigms if p.get("to") is None), paradigms[0] if paradigms else {})
    tags = current.get("tags") or []
    forms: list[Form] = []
    seen: set[str] = set()
    for inflection in current.get("inflection") or []:
        form = inflection.get("word_form")
        key = f"{form}|{','.join(inflection.get('tags') or [])}"
        if form and key not in seen:
            seen.add(key)
            forms.append(Form(form=form, tags=inflection.get("tags") or []))
    body = data.get("body") or {}
    origin = "; ".join(_render(e, concepts) for e in body.get("etymology") or []) or None
    return Article(
        dictionary=DICTIONARIES[dictionary],  # type: ignore[arg-type]
        id=data["article_id"],
        words=list(dict.fromkeys(lemma.get("lemma") for lemma in lemmas if lemma.get("lemma"))),
        word_class=next((WORD_CLASSES[t] for t in tags if t in WORD_CLASSES), None),
        gender=next((GENDERS[t] for t in tags if t in GENDERS), None),
        forms=forms,
        meanings=_meanings(body.get("definitions") or [], concepts),
        origin=origin,
        url=ARTICLE_PAGE.format(dictionary=dictionary, article_id=data["article_id"]),
    )


async def lookup(ctx: Context, args: LookupInput) -> Result[LookupOutput]:
    up = ctx.upstream(SPEC.id)
    wanted = ["bm", "nn"] if args.dictionary == "both" else [args.dictionary]
    word = args.word.strip()
    found = await up.get_json(
        f"{BASE_URL}/api/articles",
        params={"w": word, "dict": ",".join(wanted), "scope": "e"},
        ttl="search",
    )
    ids = {d: (found.json.get("articles") or {}).get(d, [])[: args.limit] for d in wanted}
    totals = {
        DICTIONARIES[d]: ((found.json.get("meta") or {}).get(d) or {}).get("total", 0)
        for d in wanted
    }
    provenance: list[Provenance] = [up.provenance(found, title=f"Ordbøkene search for '{word}'")]

    concept_fetches = {
        d: up.get_json(f"{BASE_URL}/{d}/concepts.json", ttl="concepts") for d in wanted if ids[d]
    }
    article_fetches = [
        (d, i, up.get_json(f"{BASE_URL}/{d}/article/{i}.json", ttl="article"))
        for d in wanted
        for i in ids[d]
    ]
    concept_results = dict(
        zip(concept_fetches, await asyncio.gather(*concept_fetches.values()), strict=True)
    )
    article_results = await asyncio.gather(*(fetch for _, _, fetch in article_fetches))

    articles = []
    for (d, _, _), fetched in zip(article_fetches, article_results, strict=True):
        concepts = (concept_results[d].json or {}).get("concepts") or {}
        articles.append(_article(d, fetched.json, concepts))
        provenance.append(
            up.provenance(
                fetched,
                title=f"{'Bokmålsordboka' if d == 'bm' else 'Nynorskordboka'}, "
                f"article {fetched.json.get('article_id')}",
            )
        )

    suggestions: list[str] = []
    notes = list(found.notes)
    if not articles:
        similar = await up.get_json(
            f"{BASE_URL}/api/suggest",
            params={"q": word, "dict": ",".join(wanted), "n": 5, "include": "eis"},
            ttl="search",
        )
        provenance.append(up.provenance(similar, title=f"Ordbøkene suggestions for '{word}'"))
        a = similar.json.get("a") or {}
        for key in ("exact", "inflect", "similar"):
            suggestions += [entry[0] for entry in a.get(key) or [] if entry and entry[0] != word]
        suggestions = list(dict.fromkeys(suggestions))[:5]
        notes.append(
            f"'{word}' is not a headword in the dictionaries."
            + (" Similar words are in did_you_mean." if suggestions else "")
        )
    for d in wanted:
        total = totals[DICTIONARIES[d]]
        if total > args.limit:
            notes.append(
                f"{DICTIONARIES[d].capitalize()}: showing {args.limit} of {total} articles; raise "
                "limit for more."
            )
    notes.append(f"Show this credit with the content: {CREDIT}.")
    return Result(
        data=LookupOutput(
            articles=articles, total_matches=totals, did_you_mean=suggestions, credit=CREDIT
        ),
        provenance=provenance,
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="dictionary_lookup",
        title="Look up a Norwegian word",
        description=(
            "Look a word up in Bokmålsordboka and Nynorskordboka, the official Norwegian "
            "dictionaries from the University of Bergen and Språkrådet: its meanings with "
            "examples, word class and gender, every standard inflected form, and its origin, "
            "with similar words when it is not found. Use it to check spelling, the correct "
            "form, or what a word means; the explanations are in Norwegian."
        ),
        input_model=LookupInput,
        output_model=LookupOutput,
        handler=lookup,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/dictionary",
        examples=(
            {"word": "fjord"},
            {"word": "springe", "dictionary": "nn"},
            {"word": "fjrod"},
        ),
    ),
)
