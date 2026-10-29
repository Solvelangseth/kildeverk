"""The website's Norwegian text for every source and tool.

The registry stays in English, since that is what agents read; this is what people read on the
site. A test checks that every source and tool has an entry here, so a new one cannot reach the
site untranslated.
"""

from __future__ import annotations

from typing import NamedTuple


class SourceText(NamedTuple):
    name: str
    publisher: str
    covers: list[str]
    gaps: list[str]


class ToolText(NamedTuple):
    title: str
    summary: str


SOURCES: dict[str, SourceText] = {
    "ssb_statbank": SourceText(
        "SSB Statistikkbanken",
        "Statistisk sentralbyrå (SSB)",
        [
            "Søk i alle publiserte tabeller i Statistikkbanken, på norsk eller engelsk",
            "Beskrivelse av hver tabell: dimensjoner, verdikoder, enheter, kodelister og fotnoter",
            "Tall for et hvilket som helst utvalg i en tabell, som rader med navn på hver verdi",
        ],
        [
            "Søket er SSBs eget nøkkelordsøk: det finner ord, ikke betydning",
            "Engelsk søk treffer bare engelske tabelltitler, så norske ord trenger lang='no'",
            "Koder hentet gjennom en kodeliste sjekkes ikke her; det gjør SSB",
            "Høyst 10 000 rader per kall; snevre inn utvalget for mer",
            "Tabeller fra andre PxWeb-utgivere (som Helsedirektoratet) er ikke med",
        ],
    ),
    "ssb_klass": SourceText(
        "SSB Klass",
        "Statistisk sentralbyrå (SSB)",
        [
            "Alle kommune- og fylkesnumre siden 1960, med navn og gyldighetsperiode",
            "Alle endringer: nye numre, nye navn, sammenslåinger og delinger, med datoer",
            "Omregning av kommune- og fylkestall til grensene fra 2020, 2024 eller en annen dato",
        ],
        [
            (
                "Klass registrerer endringer av kode, ikke hver liten grensejustering mellom kommuner "
                "som beholder koden; slike overføringer er usynlige for omregningen"
            ),
            (
                "En deling kan ikke regnes om nøyaktig: Klass sier hvilke områder en kommune ble delt "
                "i, men ikke hvordan innbyggerne eller andre tall fordelte seg"
            ),
            "Perioder leses per år; en endring midt i et år plasseres i det året",
            "Koder som bare gjaldt før 1960 er ikke kjent",
        ],
    ),
    "brreg": SourceText(
        "Enhetsregisteret",
        "Brønnøysundregistrene",
        [
            (
                "Alle registrerte enheter i Norge: aksjeselskap, enkeltpersonforetak, foreninger og "
                "offentlige virksomheter, med organisasjonsnummer"
            ),
            (
                "Navn, organisasjonsform, næring, adresse og kommune, antall ansatte, "
                "registreringsdatoer, aksjekapital, konkurs, avvikling og tidligere navn"
            ),
            "Underenheter (virksomheter) under en enhet",
            "Søk på navn, kommune, næring, organisasjonsform, størrelse og registreringsdato",
        ],
        [
            "Roller (styre, daglig leder, revisor) er ikke med, fordi de navngir personer",
            "Telefonnumre og e-postadresser er utelatt med vilje, selv om Brreg publiserer dem",
            (
                "Næringskodene er SN2025, som Brreg gikk over til i 2025; gamle SN2007-koder treffer "
                "ikke, men et tosifret prefiks som '62' finner som regel riktige foretak"
            ),
            "Et søk kan bla gjennom høyst 10 000 treff",
            "Regnskap ligger i et eget register; companies_accounts leser det",
        ],
    ),
    "brreg_accounts": SourceText(
        "Regnskapsregisteret",
        "Brønnøysundregistrene",
        [
            (
                "Nøkkeltall fra årsregnskapene selskapene sender inn, for de tre siste årene: "
                "driftsinntekter, driftsresultat, resultat før skatt, skatt, årsresultat, eiendeler, "
                "egenkapital, gjeld og bankinnskudd"
            ),
            (
                "Selskapsregnskap og, for morselskaper, konsernregnskap, med valuta, regnskapsregler "
                "(NGAAP eller IFRS) og om regnskapet er revidert"
            ),
        ],
        [
            "Bare de tre siste årene er åpne; eldre regnskap selger Brreg",
            (
                "Offentlige virksomheter, enkeltpersonforetak og andre uten regnskapsplikt har ingen "
                "regnskap her"
            ),
            (
                "Noter, styrets årsberetning, revisjonsberetning og kontantstrøm er ikke med i det "
                "åpne API-et"
            ),
            "Beløpene er i valutaen selskapet rapporterer i; Equinor rapporterer for eksempel i USD",
            "Små foretak kan utelate linjer som salgsinntekter eller skatt; de står da tomme",
        ],
    ),
    "met_locationforecast": SourceText(
        "MET Locationforecast",
        "Meteorologisk institutt (MET)",
        [
            (
                "Værvarsel for et hvilket som helst punkt: temperatur, nedbør, vind, skydekke, "
                "fuktighet, lufttrykk og værsymbol, time for time i omtrent 2,5 døgn og hver sjette "
                "time ut 9–10 døgn"
            ),
        ],
        [
            "Koordinatene rundes av til 3 desimaler (omtrent 110 m) før forespørselen",
            "Bruker det kompakte produktet; sannsynlighetsverdier (persentiler) er ikke med",
            "Farevarsler (MetAlerts) og havvarsler er ikke med her",
        ],
    ),
    "met_frost": SourceText(
        "MET Frost",
        "Meteorologisk institutt (MET)",
        [
            "Værstasjoner: finn dem etter posisjon eller navn, med plassering, høyde og eier",
            "Hva hver stasjon måler, og siden når",
            (
                "Klimanormaler for 1991–2020, 1961–1990 og 1931–1960: månedlig og årlig "
                "middeltemperatur og nedbør"
            ),
            (
                "Observasjoner og døgn- eller timeverdier: temperatur, nedbør, vind, snødybde, "
                "fuktighet, lufttrykk og hundrevis av andre elementer"
            ),
        ],
        [
            "Trenger en gratis klient-id fra Frost; uten den svarer verktøyene NOT_CONFIGURED",
            "Bare åpne data: serier som krever Frosts klienthemmelighet er ikke tilgjengelige",
            "Ferske observasjoner kan bruke en time eller mer på å dukke opp",
            (
                "Frost oppgir CC BY 3.0 Norge på hvert svar, mens METs generelle lisensside sier "
                "NLOD 2.0 og CC BY 4.0; svarene siterer det Frost oppgir"
            ),
        ],
    ),
    "met_metalerts": SourceText(
        "MET Farevarsler (MetAlerts)",
        "Meteorologisk institutt (MET)",
        [
            (
                "Offisielle farevarsler for land og hav: vind, kuling, regn, snø, is, stormflo, "
                "skogbrannfare, polare lavtrykk og mer, med nivå, område og råd"
            ),
            "Arkivet over tidligere farevarsler, måned for måned",
        ],
        [
            (
                "Fylkesnumrene er de som gjaldt da varselet ble sendt ut, så varsler før 2024 bruker "
                "fylkene fra 2020"
            ),
            "Varselområder kommer som navn, ikke som polygoner",
        ],
    ),
    "met_nowcast": SourceText(
        "MET nåvarsel",
        "Meteorologisk institutt (MET)",
        [
            (
                "Nedbør hvert femte minutt de neste to timene hvor som helst i Norden, fra "
                "værradar, med temperatur, vind og fuktighet nå"
            ),
        ],
        [
            "Bare Norden: Svalbard og åpent hav langt fra kysten er utenfor",
            (
                "Der radardekningen er redusert, er nedbøren mindre sikker; hvert svar sier hvor "
                "god dekningen er"
            ),
            "Bare to timer frem; weather_forecast dekker dagene etter",
        ],
    ),
    "met_oceanforecast": SourceText(
        "MET havvarsel",
        "Meteorologisk institutt (MET)",
        [
            (
                "Havvarsel for punkter langs norskekysten og i havområdene rundt: bølgehøyde og "
                "-retning, sjøtemperatur og strømfart og -retning, time for time i omtrent åtte døgn"
            ),
        ],
        [
            (
                "Punkter på land eller langt inne i en fjord har ikke varsel; hvert svar oppgir "
                "rutenettpunktet i sjøen varselet gjelder"
            ),
            "Bølgeperiode og dønning er ikke med i API-et",
        ],
    ),
    "met_airquality": SourceText(
        "MET luftkvalitetsvarsel",
        "Meteorologisk institutt (MET)",
        [
            (
                "Varsel for luftkvalitet hvor som helst i Norge, for kommunen, delområdet eller "
                "grunnkretsen: luftkvalitetsindeks og NO2, PM10, PM2,5 og ozon, time for time i "
                "omtrent to døgn"
            ),
            (
                "Hvor forurensningen kommer fra: eksos, veistøv, oppvarming (mest vedfyring), "
                "skipsfart, industri eller langtransportert forurensning"
            ),
        ],
        [
            (
                "MET kaller fortsatt API-et versjon 0.1 og har ikke endret det siden 2018, så det "
                "er mindre stabilt enn METs andre produkter"
            ),
            "Bare Norge",
            "Et modellvarsel, ikke målinger; målt luftkvalitet (NILU) er ikke med",
        ],
    ),
    "nve_hydapi": SourceText(
        "NVE HydAPI",
        "Norges vassdrags- og energidirektorat (NVE)",
        [
            (
                "NVEs hydrologiske stasjoner i elver, innsjøer, grunnvann og snø, med plassering, "
                "nedbørfelt og flomstatistikk"
            ),
            (
                "Målt vannføring, vannstand, vanntemperatur, snø, grunnvann og mer, som enkeltmålinger "
                "eller time- og døgnmiddel, helt tilbake til starten av hver serie"
            ),
        ],
        [
            "Trenger en gratis HydAPI-nøkkel; uten den svarer verktøyene NOT_CONFIGURED",
            (
                "De nyeste verdiene er ukontrollerte og kan bli rettet; hver rad sier hvor godt den "
                "er kontrollert"
            ),
            "Vannføringskurver og persentiler er ikke tatt med ennå",
            "Flom-, jordskred- og snøskredvarsler er en egen kilde (NVE Varsom)",
        ],
    ),
    "entur_geocoder": SourceText(
        "Entur stoppesteder",
        "Entur AS",
        [
            (
                "Alle stoppesteder for kollektivtrafikk i Norge fra Nasjonalt stoppestedsregister "
                "(NSR): finn dem etter navn, nær et punkt eller per kommune, med transportmidler og "
                "stoppestedstyper"
            ),
        ],
        [
            (
                "Bare stoppesteder fra NSR; adresser, interessepunkter og OpenStreetMap-steder er "
                "utelatt med vilje"
            ),
            "Grupper av stoppesteder (for eksempel en hel by) returneres ikke",
        ],
    ),
    "entur_journeyplanner": SourceText(
        "Entur reiseplanlegger",
        "Entur AS",
        [
            (
                "Avganger fra alle stoppesteder og plattformer i Norge, for alle operatører: "
                "rutetid og sanntid, plattform, linje, endestasjon, innstillinger og avviksmeldinger"
            ),
        ],
        [
            "Reiseplanlegging fra A til B er ikke tatt med ennå",
            "Sanntidsdekningen avhenger av operatøren; hver rad sier om tiden er sanntid",
            "Avganger mellomlagres i 30 sekunder",
        ],
    ),
    "kartverket": SourceText(
        "Kartverket: adresser, stedsnavn og høyde",
        "Kartverket",
        [
            (
                "Alle offisielle adresser i Norge fra matrikkelen: søk på tekst, postnummer eller "
                "kommune, eller finn adressene nærmest et punkt"
            ),
            (
                "Sentralt stedsnavnregister: fjell, vann, gårder, tettsteder og mer, med alle "
                "godkjente skrivemåter og språk (norsk, samisk, kvensk)"
            ),
            "Terrenghøyde, høyden på innsjøflater og havdybde for opptil 50 punkter",
            "Hvilken kommune og hvilket fylke et punkt ligger i, sjøterritoriet medregnet",
        ],
        [
            "Adresse-API-et gir høyst de første 10 000 treffene, og stedsnavn de første 5 000",
            "Høyde utenfor Norge og norske farvann er tom",
            "Havdybder er interpolert og må ikke brukes til navigasjon",
            "Eiendomsdata utover adressen (eiere, arealer) er ikke med",
        ],
    ),
    "norges_bank": SourceText(
        "Norges Banks åpne data",
        "Norges Bank",
        [
            (
                "Norges Banks valutakurser mot kronen for rundt 40 valutaer og indekser, daglig siden "
                "1999 (noen tidligere), med måneds- og årsgjennomsnitt"
            ),
            "Styringsrenten: nivået nå, når den sist ble endret, og alle endringer siden",
        ],
        [
            "Norges Bank oppgir ingen lisens for disse dataene; svarene sier fra om det",
            "Kursene publiseres rundt klokken 16 norsk tid på virkedager, for den dagen",
            "Andre renter (NOWA, statsobligasjoner) er ikke tatt med ennå",
        ],
    ),
    "nve_varsom": SourceText(
        "NVE Varsom",
        "Norges vassdrags- og energidirektorat (NVE), via varsom.no",
        [
            (
                "Flom- og jordskredvarsler for alle kommuner: nivå (grønt til rødt), periode, "
                "varselet, årsaker, konsekvenser og råd"
            ),
            (
                "Snøskredvarsler for alle varslingsregioner: faregrad, skredproblemer med "
                "eksposisjon og høyde, og råd"
            ),
        ],
        [
            (
                "Snøskredvarsler publiseres bare om vinteren; utenom sesongen har alle regioner "
                "faregrad 0 ('No Rating')"
            ),
            "Noen snøskredtekster finnes bare på norsk, også når engelsk er bedt om",
            (
                "Varsler er prognoser; NVE garanterer ikke at de er ferske, så sjekk varsom.no før "
                "du handler på dem"
            ),
        ],
    ),
    "nve_regobs": SourceText(
        "Regobs feltobservasjoner",
        "Norges vassdrags- og energidirektorat (NVE), via regobs.no",
        [
            (
                "Feltobservasjoner av snø og snøskred, jordskred, flom og is fra Regobs, systemet "
                "bak varsom.no: hva NVEs observatører og publikum har sett, hvor og når"
            ),
            (
                "Hver observasjons tekst (skredaktivitet, faretegn, snødekke, istykkelse, vannstand "
                "og mer), sted og kommune, observatørens brukernavn og kompetanse, og en lenke"
            ),
        ],
        [
            "Observasjonene er det folk melder inn; Regobs publiserer dem som de er",
            "Bilder telles og lenkes via observasjonens side, men returneres ikke",
            (
                "Regobs krever at observatøren krediteres med brukernavn, så det returneres; et "
                "brukernavn som er en e-postadresse, kuttes så det ikke lenger er en"
            ),
        ],
    ),
    "datanorge": SourceText(
        "data.norge.no",
        "Digitaliseringsdirektoratet (Digdir)",
        [
            (
                "Norges nasjonale datakatalog: datasett og API-er som offentlige virksomheter "
                "beskriver, søkbare på tekst, tema, utgiver, format, åpne data og nylige endringer"
            ),
        ],
        [
            (
                "Finner beskrivelser av data, ikke selve dataene; hvert treff lenker til sin side i "
                "katalogen"
            ),
            "Kvaliteten avhenger av hva hver utgiver har skrevet",
            (
                "Filtrering på utgiver trenger organisasjonsstien som treffene har, for eksempel "
                "'/STAT/972417807/971526920'"
            ),
            "Begreper, informasjonsmodeller og offentlige tjenester i katalogen søkes ikke i",
        ],
    ),
    "kartverket_sea_level": SourceText(
        "Kartverket vannstand og tidevann",
        "Kartverket, sjødivisjonen",
        [
            (
                "Vannstand langs hele norskekysten: målt ved rundt 25 faste vannstandsmålere, "
                "modellert ellers, med tidevannsprognose, værets virkning og varsel noen dager frem"
            ),
            "Tidevannstabeller: tidspunkt og høyde for høyvann og lavvann",
        ],
        [
            (
                "Borte fra en vannstandsmåler er alle verdier modellert; målinger finnes bare ved "
                "målerne"
            ),
            "Posisjoner innlands eller langt til havs har ingen data",
            "Returnivåer (100-årsstormflo og lignende) er ikke tatt med ennå",
        ],
    ),
    "nve_reservoirs": SourceText(
        "NVE magasinstatistikk",
        "Norges vassdrags- og energidirektorat (NVE)",
        [
            (
                "Hvor fulle vannmagasinene er, ukentlig siden 1995: fyllingsgrad og TWh for hele "
                "landet og hvert prisområde (NO1–NO5)"
            ),
            "Laveste, median og høyeste fylling for hver uke de siste 20 årene",
        ],
        [
            "Bare ukentlige tall, publisert på onsdager for uken før",
            "Enkeltmagasiner publiseres ikke; bare summer per område",
        ],
    ),
    "elhub": SourceText(
        "Elhub energidata",
        "Elhub AS",
        [
            (
                "Strømforbruk i hver kommune, time for time siden 2021, fordelt på privatkunder "
                "(boliger og hytter), næring (tjenester) og industri, med antall målepunkter"
            ),
            (
                "Installert produksjonskapasitet i hver kommune etter type: vann, vind, sol, termisk "
                "og annet, og hvor mye av den som er hos plusskunder"
            ),
            (
                "Forbruk og produksjon i hvert prisområde (NO1–NO5): forbruk hos husholdninger, hytter "
                "og primær-, sekundær- og tertiærnæring; produksjon fra vann, vind, sol, termisk og "
                "annet"
            ),
        ],
        [
            "Elhub gir kommunetall én dag per forespørsel, så et kall dekker høyst 31 dager",
            (
                "Produksjon per kommune er ikke med: Elhubs kommunetall gjelder bare plusskunder og "
                "ville undervurdert steder med kraftverk kraftig, så bare kapasiteten vises"
            ),
            (
                "Tallene er slik nettselskapene rapporterer dem, og Elhub retter dem når sene eller "
                "korrigerte målerverdier kommer inn; de siste dagene er minst sikre"
            ),
            "Utveksling mellom prisområder, kvartersverdier og Norgespris er ikke tatt med ennå",
            "Datasett etter næringskode eller leverandør krever Maskinporten og brukes ikke",
        ],
    ),
    "stortinget": SourceText(
        "Stortingets åpne data",
        "Stortinget",
        [
            (
                "Alle saker på Stortinget per sesjon: lovforslag, budsjetter og andre saker, med "
                "komité, status, type og vedtak"
            ),
            (
                "Hvordan Stortinget stemte i en sak: resultatet, stemmetallene, og hvordan hvert parti "
                "stemte når det var navneopprop"
            ),
            "Stortingsrepresentantene: parti, valgkrets og komiteer, nå eller for en periode",
        ],
        [
            "Mange voteringer er uten navneopprop, uten tall eller navn; svarene sier fra",
            "Spørsmål til statsrådene, høringer og debatter er ikke tatt med ennå",
            "Kontaktinformasjon og fødselsdatoer for representantene er utelatt",
        ],
    ),
    "vegvesen_traffic": SourceText(
        "Statens vegvesen trafikkdata",
        "Statens vegvesen",
        [
            (
                "Rundt 10 000 trafikkregistreringspunkter på veier og sykkelveier, med vei, kommune, "
                "posisjon og hvor lenge hvert punkt har talt"
            ),
            (
                "Kjøretøy per time eller per døgn ved et punkt, etter retning og lengde, og "
                "årsdøgntrafikk (ÅDT) for hvert år som er talt"
            ),
        ],
        [
            "Time er den fineste oppløsningen; enkeltkjøretøy og fart er ikke offentlig",
            "Tallene er bare så fullstendige som dekningen, som hver rad oppgir",
            "Trafikkindekser og Nasjonal vegdatabank (NVDB) er ikke tatt med ennå",
        ],
    ),
    "udir_nsr": SourceText(
        "Nasjonalt skoleregister (NSR)",
        "Utdanningsdirektoratet (Udir)",
        [
            (
                "Alle grunnskoler og videregående skoler i Norge, offentlige og private, og norske "
                "skoler i utlandet: navn, kommune, eierform, trinn og antall elever"
            ),
        ],
        [
            "Barnehager ligger i et annet register og er ikke med",
            "Elevtallet er registerets siste tall, ikke en tidsserie",
            "Resultater, lærertetthet og annen skolestatistikk er ikke med",
        ],
    ),
    "usgs_earthquakes": SourceText(
        "USGS jordskjelvkatalog",
        "U.S. Geological Survey (USGS)",
        [
            (
                "Jordskjelv i hele verden fra USGS-katalogen, nær et hvilket som helst punkt: tid, "
                "styrke, dybde, sted, om USGS har kontrollert det, hvor mange som meldte at de "
                "kjente det, og en lenke til hendelsen"
            ),
        ],
        [
            (
                "Utenfor USA mangler katalogen mange skjelv under omtrent styrke 4; Norsk "
                "Nasjonalt Seismisk Nettverk registrerer de mindre norske, men lisensen er uklar, "
                "så det brukes ikke"
            ),
            "Nye hendelser er automatiske anslag først og kan bli endret",
        ],
    ),
}


TOOLS: dict[str, ToolText] = {
    "place_overview": ToolText(
        "Oversikt over et sted",
        "Alt om et punkt i ett kall: kommune, høyde, været nå, om det blir regn snart, "
        "farevarsler, nærmeste holdeplasser og stedsnavn.",
    ),
    "municipality_profile": ToolText(
        "Profil av en kommune",
        "Folketall og endring, foretak og største arbeidsgivere med omsetning, skoler, "
        "trafikkpunkter, strømforbruk og farevarsler for én kommune.",
    ),
    "compare_municipalities": ToolText(
        "Sammenlign kommuner",
        "To til fem kommuner side om side, med foretak per 1 000 innbyggere og strøm per "
        "innbygger.",
    ),
    "statistics_search_tables": ToolText(
        "Søk i SSBs tabeller",
        "Finn tabeller i Statistikkbanken etter nøkkelord. Start her for offisiell statistikk.",
    ),
    "statistics_describe_table": ToolText(
        "Beskriv en SSB-tabell",
        "Se hva en tabell inneholder før du henter tall: dimensjoner, koder, enheter og fotnoter.",
    ),
    "statistics_get_data": ToolText(
        "Hent tall fra en SSB-tabell",
        "Hent et utvalg av en tabell som rader med navn på hver verdi.",
    ),
    "statistics_series": ToolText(
        "En statistikk over tid",
        "Én statistikk for et sted, år for år, uten brudd ved kommunereformene i 2020 og 2024.",
    ),
    "statistics_rank": ToolText(
        "Ranger kommuner eller fylker",
        "Alle kommuner eller fylker rangert på én statistikk, eller på endringen siden et "
        "tidligere år.",
    ),
    "regions_list": ToolText(
        "List kommuner eller fylker",
        "Alle kommuner eller fylker med nummer og navn, i dag eller på en dato siden 1960.",
    ),
    "regions_resolve": ToolText(
        "Finn en kommune eller et fylke",
        "Slå opp på navn eller nummer, også tidligere kommuner, og se hva de er en del av i dag.",
    ),
    "regions_changes": ToolText(
        "Endringer i kommuner og fylker",
        "Sammenslåinger, delinger, nye numre og nye navn mellom to datoer.",
    ),
    "regions_harmonise": ToolText(
        "Regn om til andre grenser",
        "Regn om tall per kommune eller fylke til grensene på en annen dato, så serier henger "
        "sammen.",
    ),
    "regions_at_point": ToolText(
        "Kommune og fylke for et punkt",
        "Hvilken kommune og hvilket fylke en koordinat ligger i, i dag eller på en tidligere dato.",
    ),
    "weather_forecast": ToolText(
        "Værvarsel for et punkt",
        "Temperatur, nedbør, vind og mer for en hvilken som helst koordinat, opptil ti døgn frem.",
    ),
    "weather_nowcast": ToolText(
        "Regn de neste to timene",
        "Nedbør hvert femte minutt fra radar, når regnet starter eller slutter, og været nå.",
    ),
    "air_quality_forecast": ToolText(
        "Luftkvalitetsvarsel",
        "Luftkvalitet time for time i to døgn, med forurensningen bak og hvor den kommer fra.",
    ),
    "sea_forecast": ToolText(
        "Bølger og sjøtemperatur",
        "Bølgehøyde, sjøtemperatur og strøm langs kysten, time for time i opptil åtte døgn.",
    ),
    "weather_normals": ToolText(
        "Normaler ved en værstasjon",
        "Normaltemperatur og -nedbør for 1991–2020, og hvor varm og våt hver måned i et år var "
        "mot normalen.",
    ),
    "weather_warnings": ToolText(
        "Farevarsler for vær",
        "METs offisielle farevarsler for land og hav, med nivå, område, periode og råd.",
    ),
    "weather_find_stations": ToolText(
        "Finn værstasjoner",
        "METs værstasjoner nær et punkt eller etter navn.",
    ),
    "weather_station_elements": ToolText(
        "Hva en værstasjon måler",
        "Hvilke elementer en stasjon måler, i hvilken oppløsning og over hvilke år.",
    ),
    "weather_observations": ToolText(
        "Målt vær ved en stasjon",
        "Timeverdier eller døgn- og månedsverdier fra en værstasjon, helt tilbake til den åpnet.",
    ),
    "water_find_stations": ToolText(
        "Finn hydrologiske stasjoner",
        "NVEs stasjoner i elver, innsjøer, snø og grunnvann, etter navn, sted eller avstand.",
    ),
    "water_observations": ToolText(
        "Målt vannføring og vannstand",
        "Vannføring, vannstand, vanntemperatur, snø og mer ved en NVE-stasjon.",
    ),
    "energy_reservoirs": ToolText(
        "Fyllingsgrad i vannmagasinene",
        "Hvor fulle vannmagasinene er, for landet og hvert prisområde, mot de siste 20 årene.",
    ),
    "electricity_municipality": ToolText(
        "Strømforbruk i en kommune",
        "Forbruk per dag eller time for privatkunder, næring og industri, og installert "
        "produksjonskapasitet etter type.",
    ),
    "electricity_price_areas": ToolText(
        "Strøm per prisområde",
        "Forbruk og produksjon i NO1–NO5 per dag, etter forbruksgruppe og kraftkilde.",
    ),
    "hazards_flood_landslide": ToolText(
        "Flom- og jordskredvarsler",
        "NVEs varsler fra varsom.no for landet, et fylke eller en kommune.",
    ),
    "hazards_earthquakes": ToolText(
        "Jordskjelv nær et punkt",
        "Jordskjelv fra USGS med tid, styrke, dybde og avstand, de nyeste eller de største først.",
    ),
    "hazards_field_observations": ToolText(
        "Feltobservasjoner av skred, flom og is",
        "Hva folk har sett i terrenget: skredaktivitet, faretegn, jordskred, vannstand og is.",
    ),
    "hazards_avalanche": ToolText(
        "Snøskredvarsler",
        "Faregrad, skredproblemer og råd for hver varslingsregion.",
    ),
    "addresses_search": ToolText(
        "Søk etter adresser",
        "Offisielle adresser fra matrikkelen, etter tekst, postnummer, kommune eller nærhet.",
    ),
    "places_search": ToolText(
        "Søk etter stedsnavn",
        "Fjell, vann, elver, øyer, gårder og tettsteder fra stedsnavnregisteret.",
    ),
    "terrain_elevation": ToolText(
        "Høyde over havet",
        "Høyde for opptil 50 punkter, fra Kartverkets terrengmodell; havdybde til sjøs.",
    ),
    "sea_level": ToolText(
        "Vannstand og tidevann",
        "Målt og varslet vannstand langs kysten, eller en tabell over høyvann og lavvann.",
    ),
    "transit_find_stops": ToolText(
        "Finn holdeplasser",
        "Buss-, trikk-, T-bane-, tog-, ferje- og flyplasstopp i hele Norge.",
    ),
    "transit_departures": ToolText(
        "Neste avganger",
        "Neste buss, tog, trikk, T-bane eller ferje fra en holdeplass, med sanntid, forsinkelser "
        "og avvik.",
    ),
    "traffic_find_points": ToolText(
        "Finn trafikktellepunkter",
        "Statens vegvesens tellepunkter etter navn, kommune, vei eller avstand.",
    ),
    "traffic_volumes": ToolText(
        "Trafikkmengde ved et punkt",
        "Kjøretøy per time eller døgn, etter retning og størrelse, eller ÅDT per år.",
    ),
    "companies_search": ToolText(
        "Søk etter virksomheter",
        "Søk i Enhetsregisteret etter navn, kommune, næring, organisasjonsform og størrelse.",
    ),
    "companies_get": ToolText(
        "Slå opp en virksomhet",
        "Én virksomhet etter organisasjonsnummer, med næring, ansatte, adresser og underenheter.",
    ),
    "companies_accounts": ToolText(
        "Årsregnskap for et selskap",
        "Driftsinntekter, resultat, egenkapital og gjeld fra de tre siste årsregnskapene, med "
        "driftsmargin og egenkapitalandel.",
    ),
    "schools_search": ToolText(
        "Finn skoler",
        "Grunnskoler og videregående skoler etter navn, kommune eller fylke.",
    ),
    "schools_get": ToolText(
        "Én skole",
        "Elever, ansatte, trinn, eier, målform, adresse og nettside for én skole.",
    ),
    "currency_exchange_rates": ToolText(
        "Valutakurser mot kronen",
        "Norges Banks kurser for rundt 40 valutaer, daglig eller som gjennomsnitt.",
    ),
    "rates_policy_rate": ToolText(
        "Styringsrenten",
        "Nivået nå, når det trådte i kraft, og alle endringer siden en dato.",
    ),
    "parliament_cases": ToolText(
        "Søk i Stortingets saker",
        "Saker i en sesjon, filtrert på ord i tittelen, type, status eller komité.",
    ),
    "parliament_case": ToolText(
        "En sak og voteringene",
        "Én sak med vedtaket og hver votering, også hvordan partiene stemte.",
    ),
    "parliament_members": ToolText(
        "Stortingsrepresentantene",
        "Representantene i dag eller i en periode, med parti, valgkrets og komiteer.",
    ),
    "catalog_search": ToolText(
        "Søk i datakatalogen",
        "Finn datasett og API-er som offentlige virksomheter har beskrevet på data.norge.no.",
    ),
    "cite_sources": ToolText(
        "Kildehenvisninger for et svar",
        "Gjør kildene i et svar om til BibTeX og CSL-JSON for Zotero, Pandoc og lignende.",
    ),
    "sources_list": ToolText(
        "List kildene",
        "Alle kildene tjenesten leser fra, med lisens, grenser og kjente hull.",
    ),
    "service_status": ToolText(
        "Tjenestestatus",
        "Hvor mye av kvoten som er igjen hos hver kilde, og hvordan verktøyene er brukt.",
    ),
}


# How the site groups the tools: by what people want to know, not by publisher.
THEMES: list[tuple[str, str, list[str]]] = [
    (
        "Samlede svar",
        "Ett kall som henter fra flere kilder samtidig.",
        ["place_overview", "municipality_profile", "compare_municipalities"],
    ),
    (
        "Statistikk",
        "Alt SSB publiserer i Statistikkbanken.",
        [
            "statistics_search_tables",
            "statistics_describe_table",
            "statistics_get_data",
            "statistics_series",
            "statistics_rank",
        ],
    ),
    (
        "Kommuner og fylker",
        "Numre, navn og grenser, også før reformene.",
        [
            "regions_resolve",
            "regions_list",
            "regions_changes",
            "regions_harmonise",
            "regions_at_point",
        ],
    ),
    (
        "Vær og klima",
        "Varsler, farevarsler, luftkvalitet og målinger fra Meteorologisk institutt.",
        [
            "weather_nowcast",
            "weather_forecast",
            "air_quality_forecast",
            "weather_warnings",
            "weather_find_stations",
            "weather_station_elements",
            "weather_observations",
            "weather_normals",
        ],
    ),
    (
        "Vann, energi og naturfare",
        "Elver, magasiner, strøm, flom, skred og jordskjelv fra NVE, Elhub og USGS.",
        [
            "water_find_stations",
            "water_observations",
            "energy_reservoirs",
            "electricity_municipality",
            "electricity_price_areas",
            "hazards_flood_landslide",
            "hazards_avalanche",
            "hazards_earthquakes",
            "hazards_field_observations",
        ],
    ),
    (
        "Kart, steder og havet",
        "Adresser, stedsnavn og høyder fra Kartverket, vannstand og havvarsel.",
        ["addresses_search", "places_search", "terrain_elevation", "sea_level", "sea_forecast"],
    ),
    (
        "Reise og trafikk",
        "Kollektivtrafikk fra Entur og veitrafikk fra Statens vegvesen.",
        ["transit_find_stops", "transit_departures", "traffic_find_points", "traffic_volumes"],
    ),
    (
        "Virksomheter og skoler",
        "Enhetsregisteret, Regnskapsregisteret og Nasjonalt skoleregister.",
        [
            "companies_search",
            "companies_get",
            "companies_accounts",
            "schools_search",
            "schools_get",
        ],
    ),
    (
        "Penger og renter",
        "Valutakurser og styringsrenten fra Norges Bank.",
        ["currency_exchange_rates", "rates_policy_rate"],
    ),
    (
        "Stortinget",
        "Saker, voteringer og representanter.",
        ["parliament_cases", "parliament_case", "parliament_members"],
    ),
    (
        "Datakatalog og tjenesten",
        "Finn andre datasett, lag kildehenvisninger og se status.",
        ["catalog_search", "cite_sources", "sources_list", "service_status"],
    ),
]


# Short Norwegian names for the publishers the recipes cite.
PUBLISHERS: dict[str, str] = {
    "Statistics Norway (SSB)": "SSB",
    "Brønnøysund Register Centre (Brønnøysundregistrene)": "Brønnøysundregistrene",
    "Norwegian Meteorological Institute (MET Norway)": "Meteorologisk institutt",
    "Norwegian Water Resources and Energy Directorate (NVE)": "NVE",
    "Norwegian Water Resources and Energy Directorate (NVE), via varsom.no": "NVE (varsom.no)",
    "Norwegian Water Resources and Energy Directorate (NVE), via regobs.no": "NVE (regobs.no)",
    "Entur AS": "Entur",
    "Norwegian Mapping Authority (Kartverket)": "Kartverket",
    "Norwegian Mapping Authority, Hydrographic Service (Kartverket)": "Kartverket",
    "Norges Bank": "Norges Bank",
    "Norwegian Digitalisation Agency (Digdir), data.norge.no": "Digdir",
    "Stortinget (the Norwegian parliament)": "Stortinget",
    "Norwegian Public Roads Administration (Statens vegvesen)": "Statens vegvesen",
    "Norwegian Directorate for Education and Training (Udir)": "Udir",
    "Elhub AS": "Elhub",
    "U.S. Geological Survey (USGS)": "USGS",
}

LICENCES: dict[str, str] = {"not-stated": "ingen lisens oppgitt"}
