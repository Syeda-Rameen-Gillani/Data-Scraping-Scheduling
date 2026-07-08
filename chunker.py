import re


def chunk_text(text, chunk_size=700, overlap=100):
    """
    Paragraph-aware chunking for long-form judgment text extracted from PDF.

    Judgments extracted via PyMuPDF have no headers or markdown structure --
    they're continuous prose broken into paragraphs by blank/whitespace-only
    lines, with Windows-style \\r\\n line endings from the source PDFs.
    Blindly slicing by character count (the previous approach) ignores those
    natural boundaries and routinely cuts a chunk off mid-sentence or
    mid-word, which hurts both embedding quality (a half-sentence embeds
    poorly) and readability of the excerpt shown back to the user as a
    citation.

    This groups whole paragraphs together up to `chunk_size` characters, so
    chunk boundaries land on paragraph/sentence breaks wherever possible. A
    single paragraph longer than `chunk_size` falls back to a sliding window
    over just that paragraph, since there's no smaller natural boundary left
    to respect.

    NOTE: this function is only used for the free-form PDF/judgment text.
    Scraped structured metadata (case_no, citation, topic, code) is short,
    atomic key/value data attached directly as Weaviate properties on each
    chunk -- it is never passed through this function, since splitting a
    single field like "HCA 1/2023" into overlapping windows would destroy
    its meaning rather than aid retrieval. See DECISIONS.md for the full
    rationale.
    """
    # Normalize line endings and strip trailing whitespace from each line so
    # "blank" lines that actually contain stray spaces still count as breaks.
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)

    # Split into paragraphs on one-or-more blank lines.
    raw_paragraphs = re.split(r"\n\s*\n+", normalized)

    paragraphs = []
    for para in raw_paragraphs:
        # Join wrapped lines within a paragraph into a single readable line
        # (PDF line breaks are visual wrapping, not sentence boundaries).
        joined = " ".join(line.strip() for line in para.split("\n") if line.strip())
        if joined:
            paragraphs.append(joined)

    chunks = []
    current = ""

    for para in paragraphs:
        if len(para) > chunk_size:
            # This single paragraph is bigger than a whole chunk -- flush
            # whatever we were building, then slide a window over just it.
            if current:
                chunks.append(current.strip())
                current = ""
            start = 0
            while start < len(para):
                end = start + chunk_size
                chunks.append(para[start:end].strip())
                start = end - overlap
            continue

        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            chunks.append(current.strip())
            # Carry a bit of the previous chunk forward as overlap, so
            # context isn't lost right at the seam between chunks.
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n\n{para}".strip() if tail else para

    if current:
        chunks.append(current.strip())

    return chunks