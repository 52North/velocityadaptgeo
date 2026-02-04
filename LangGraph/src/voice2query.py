from typing import Optional
from bs4 import BeautifulSoup
from io import StringIO
from markdown import Markdown
from pathlib import Path
from typing import Optional, Dict, Any
import json
from distro import name
from openai import OpenAI
import pandas as pd
import re

# Initialize OpenAI client
client = OpenAI()


def transcribe_audio_bytes(audio_bytes: bytes, filename: str = "audio.webm") -> dict:
    """
    unction to convert audio bytes to text using OpenAI's transcription model whisper    
    :param audio_bytes: Description
    :type audio_bytes: bytes
    :param filename: Description
    :type filename: str
    :return: Description
    :rtype: dict
    """

    import io
    f = io.BytesIO(audio_bytes)
    f.name = filename

    transcription = client.audio.transcriptions.create(
        model="gpt-4o-mini-transcribe",
        file=f,
    )

    # call the function to edit the query with name correction
    result = edit_query_with_name(transcription.text)

    return {
        "text": transcription.text,
        "result": result
    }


def edit_query_with_name(input_txt: str) -> dict:
    """
    query: str,
        :return: Description
        :rtype: dict
        """
    name = handle_query(input_txt)

    match = handle_query(llm_pick_name(name, extract_unique_names()))

    new_query = replace_name_in_query(
        input_txt,
        name,
        match,
    )

    return {
        "match": match,
        "name": name,
        "corrected_query": new_query,
    }


def handle_query(text: str) -> Optional[str]:
    """
    function to handle a query text and extract a name
    :param text: Description
    :type text: str
    :return: Description
    :rtype: str | None
    """
    name = extract_name(text)

    if name:
        print(f"Name gefunden: {name}")
    else:
        print("Kein Name im Text")

    return name


# function to extract a person name from text using OpenAI's language model
def extract_name(text: str) -> Optional[str]:
    """
    Extracts ONE person name from the text.
    Returns the name as a string, or None if no person name is mentioned.
    """
    prompt = f"""
    Extract the single most likely PERSON NAME from this text.
    If there is no person name, return null.
    Return ONLY valid JSON, like:
    {{"name": "Christian Knoth"}} or {{"name": null}}

    Text:
    {text}
    """

    # Call OpenAI's language model
    resp = client.responses.create(
        model="gpt-4o-mini",
        input=prompt,
        temperature=0.0,  # smae text = same output
    )
    # Parse the response
    raw = resp.output_text.strip()
    try:
        data = json.loads(raw)
        name = data.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    except Exception:
        pass

    return None


# cleaning and extracting names from Excel file
# ---- Konfiguration ----

BASE_DIR = Path(__file__).resolve().parent
EXCEL_PATH = BASE_DIR.parent / "data" / "revised01_ifgi.csv"
NAME_COLUMN = "Name (akad. Grad, Vorname, Nachname"

# ---- Titel-Pattern ----
TITLE_PATTERN = re.compile(
    r"\b("
    r"Dr\.?|"
    r"Prof\.?|"
    r"PD|"
    r"Dipl\.-Ing\.?|"
    r"M\.Sc\.?|"
    r"B\.Sc\.?|"
    r"Ph\.D\.?|"
    r"Univ\.-Prof\.?"
    r")\b",
    flags=re.IGNORECASE,
)


def clean_name(raw_name: str) -> str:
    """deltede titles and extra spaces from a name string"""
    if not isinstance(raw_name, str):
        return ""

    # Titel entfernen
    name = TITLE_PATTERN.sub("", raw_name)

    # Mehrfach-Leerzeichen entfernen
    name = re.sub(r"\s+", " ", name)

    return name.strip()


def extract_unique_names() -> list[str]:
    """read Excel file and extract unique cleaned names"""
    df = pd.read_csv(
        EXCEL_PATH,
        sep=";",          # ← DAS ist der Schlüssel
        encoding="utf-8"
    )

    NAME_COLUMN = "Name (akad. Grad, Vorname, Nachname)"

    # cleaned_names = df.columns.tolist()

    cleaned_names = (
        df[NAME_COLUMN]
        .dropna()
        .apply(clean_name)
        .loc[lambda s: s != ""]
        .unique()
        .tolist()
    )
    print(f"Extracted {len(cleaned_names)} unique cleaned names.")
    return cleaned_names


client = OpenAI()


def llm_pick_name(extracted_name: str, candidates: list[str]) -> str | None:
    prompt = f"""
    You are matching a person name that may contain transcription errors.
    Pick the best matching candidate from the list, or null if none match well.

    Return ONLY JSON:
    {{"match": "<exact candidate from list>"}} or {{"match": null}}

    Extracted name: {extracted_name}

    Candidate list:
    {json.dumps(candidates, ensure_ascii=False)}
    """
    resp = client.responses.create(
        model="gpt-4o-mini",
        input=prompt,
        temperature=0.0,
    )

    raw = resp.output_text.strip()
    # name = markdown_to_text(raw)
    return raw


# Source - https://stackoverflow.com/a
# Posted by Pavel Vorobyov
# Retrieved 2026-01-10, License - CC BY-SA 4.0


def markdown_to_text(markdown_string):
    """ Converts a markdown string to plaintext """

    # md -> html -> text since BeautifulSoup can extract text cleanly
    html = Markdown(markdown_string)

    # remove code snippets
    html = re.sub(r'<pre>(.*?)</pre>', ' ', html)
    html = re.sub(r'<code>(.*?)</code >', ' ', html)

    # extract text
    soup = BeautifulSoup(html, "html.parser")
    text = ''.join(soup.findAll(text=True))

    return text


def replace_name_in_query(
    query: str,
    extracted_name: Optional[str],
    corrected_name: Optional[str],
) -> str:
    """
    Ersetzt extracted_name im query durch corrected_name.
    Falls etwas fehlt → Original-Query zurück.
    """
    if not query or not extracted_name or not corrected_name:
        return query

    # Escape für Regex (falls Sonderzeichen im Namen sind)
    pattern = re.escape(extracted_name)

    # Case-insensitive, aber nur exakte Wortfolge
    replaced_query = re.sub(
        pattern,
        corrected_name,
        query,
        flags=re.IGNORECASE,
    )

    return replaced_query
