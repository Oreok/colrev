#!/usr/bin/env python3
import os
import re
import subprocess
import time
from pathlib import Path
from xml.etree.ElementTree import Element

import requests
from lxml import etree

ns = {
    "tei": "{http://www.tei-c.org/ns/1.0}",
    "w3": "{http://www.w3.org/XML/1998/namespace}",
}
nsmap = {
    "tei": "http://www.tei-c.org/ns/1.0",
    "w3": "http://www.w3.org/XML/1998/namespace",
}

GROBID_URL = "http://localhost:8070"


def start_grobid() -> bool:
    r = requests.get(GROBID_URL + "/api/isalive")
    if r.text == "true":
        # print('Docker running')
        return True
    print("Starting grobid service...")
    subprocess.Popen(
        [
            'docker run -t --rm -m "4g" -p 8070:8070 '
            + "-p 8071:8071 lfoppiano/grobid:0.6.2"
        ],
        shell=True,
        stdin=None,
        stdout=open(os.devnull, "wb"),
        stderr=None,
        close_fds=True,
    )
    pass

    i = 0
    while True:
        i += 1
        time.sleep(1)
        r = requests.get(GROBID_URL + "/api/isalive")
        if r.text == "true":
            print("Grobid service alive.")
            return True
        if i > 30:
            break
    return False


def get_root_tei_data(fpath: Path):
    from colrev_core import grobid_client

    options = {}
    # options["consolidateCitations"] = "1"
    options["consolidateCitations"] = "0"
    r = requests.post(
        grobid_client.get_grobid_url() + "/api/processFulltextDocument",
        files={"input": open(str(fpath), "rb")},
        data=options,
    )
    data = r.content

    return data


def get_paper_title(root: Element) -> str:
    title_text = "NA"
    file_description = root.find(".//" + ns["tei"] + "fileDesc")
    if file_description is not None:
        titleStmt_node = file_description.find(".//" + ns["tei"] + "titleStmt")
        if titleStmt_node is not None:
            title_node = titleStmt_node.find(".//" + ns["tei"] + "title")
            if title_node is not None:
                title_text = title_node.text if title_node.text is not None else "NA"
                title_text = (
                    title_text.replace("(Completed paper)", "")
                    .replace("(Completed-paper)", "")
                    .replace("(Research-in-Progress)", "")
                    .replace("Completed Research Paper", "")
                )
    return title_text


def get_paper_journal(root: Element) -> str:
    journal_name = "NA"
    file_description = root.find(".//" + ns["tei"] + "sourceDesc")
    if file_description is not None:
        if file_description.find(".//" + ns["tei"] + "monogr") is not None:
            journal_node = file_description.find(".//" + ns["tei"] + "monogr")
            if journal_node is not None:
                jtitle_node = journal_node.find(".//" + ns["tei"] + "title")
                if jtitle_node is not None:
                    journal_name = (
                        jtitle_node.text if jtitle_node.text is not None else "NA"
                    )
                    if "NA" != journal_name:
                        words = journal_name.split()
                        if sum(word.isupper() for word in words) / len(words) > 0.8:
                            words = [word.capitalize() for word in words]
                            journal_name = " ".join(words)
    return journal_name


def get_paper_journal_volume(root: Element) -> str:
    volume = "NA"
    file_description = root.find(".//" + ns["tei"] + "sourceDesc")
    if file_description is not None:
        if file_description.find(".//" + ns["tei"] + "monogr") is not None:
            journal_node = file_description.find(".//" + ns["tei"] + "monogr")
            if journal_node is not None:
                imprint_node = journal_node.find(".//" + ns["tei"] + "imprint")
                if imprint_node is not None:
                    vnode = imprint_node.find(
                        ".//" + ns["tei"] + "biblScope[@unit='volume']"
                    )
                    if vnode is not None:
                        volume = vnode.text if vnode.text is not None else "NA"
    return volume


def get_paper_journal_issue(root: Element) -> str:
    issue = "NA"
    file_description = root.find(".//" + ns["tei"] + "sourceDesc")
    if file_description is not None:
        if file_description.find(".//" + ns["tei"] + "monogr") is not None:
            journal_node = file_description.find(".//" + ns["tei"] + "monogr")
            if journal_node is not None:
                imprint_node = journal_node.find(".//" + ns["tei"] + "imprint")
                if imprint_node is not None:
                    issue_node = imprint_node.find(
                        ".//" + ns["tei"] + "biblScope[@unit='issue']"
                    )
                    if issue_node is not None:
                        issue = issue_node.text if issue_node.text is not None else "NA"
    return issue


def get_paper_journal_pages(root: Element) -> str:
    pages = "NA"
    file_description = root.find(".//" + ns["tei"] + "sourceDesc")
    if file_description is not None:
        journal_node = file_description.find(".//" + ns["tei"] + "monogr")
        if journal_node is not None:
            imprint_node = journal_node.find(".//" + ns["tei"] + "imprint")
            if imprint_node is not None:
                page_node = imprint_node.find(
                    ".//" + ns["tei"] + "biblScope[@unit='page']"
                )
                if page_node is not None:
                    if (
                        page_node.get("from") is not None
                        and page_node.get("to") is not None
                    ):
                        pages = (
                            page_node.get("from", "") + "--" + page_node.get("to", "")
                        )
    return pages


def get_paper_year(root: Element) -> str:
    year = "NA"
    file_description = root.find(".//" + ns["tei"] + "sourceDesc")
    if file_description is not None:
        if file_description.find(".//" + ns["tei"] + "monogr") is not None:
            journal_node = file_description.find(".//" + ns["tei"] + "monogr")
            if journal_node is not None:
                imprint_node = journal_node.find(".//" + ns["tei"] + "imprint")
                if imprint_node is not None:
                    date_node = imprint_node.find(".//" + ns["tei"] + "date")
                    if date_node is not None:
                        year = (
                            date_node.get("when", "")
                            if date_node.get("when") is not None
                            else "NA"
                        )
                        year = re.sub(r".*([1-2][0-9]{3}).*", r"\1", year)
    return year


def get_author_name_from_node(author_node) -> str:
    authorname = ""

    author_pers_node = author_node.find(ns["tei"] + "persName")
    if author_pers_node is None:
        return authorname
    surname_node = author_pers_node.find(ns["tei"] + "surname")
    if surname_node is not None:
        surname = surname_node.text if surname_node.text is not None else ""
    else:
        surname = ""

    forename_node = author_pers_node.find(ns["tei"] + 'forename[@type="first"]')
    if forename_node is not None:
        forename = forename_node.text if forename_node.text is not None else ""
    else:
        forename = ""

    if 1 == len(forename):
        forename = forename + "."

    middlename_node = author_pers_node.find(ns["tei"] + 'forename[@type="middle"]')
    if middlename_node is not None:
        middlename = (
            " " + middlename_node.text if middlename_node.text is not None else ""
        )
    else:
        middlename = ""

    if 1 == len(middlename):
        middlename = middlename + "."

    authorname = surname + ", " + forename + middlename

    authorname = (
        authorname.replace("\n", " ")
        .replace("\r", "")
        .replace("•", "")
        .replace("+", "")
        .replace("Dipl.", "")
        .replace("Prof.", "")
        .replace("Dr.", "")
        .replace("&apos", "'")
        .replace("❚", "")
        .replace("~", "")
        .replace("®", "")
        .replace("|", "")
    )

    authorname = re.sub("^Paper, Short; ", "", authorname)
    return authorname


def get_paper_authors(root: Element) -> str:
    author_string = "NA"
    file_description = root.find(".//" + ns["tei"] + "sourceDesc")
    author_list = []

    if file_description is not None:
        if file_description.find(".//" + ns["tei"] + "analytic") is not None:
            analytic_node = file_description.find(".//" + ns["tei"] + "analytic")
            if analytic_node is not None:
                for author_node in analytic_node.iterfind(ns["tei"] + "author"):

                    authorname = get_author_name_from_node(author_node)
                    if ", " != authorname and "" != authorname:
                        author_list.append(authorname)

                author_string = " and ".join(author_list)

                # TODO: deduplicate
                if author_string is None:
                    author_string = "NA"
                if "" == author_string.replace(" ", "").replace(",", "").replace(
                    ";", ""
                ):
                    author_string = "NA"
    return author_string


def get_paper_doi(root: Element) -> str:
    doi = "NA"
    file_description = root.find(".//" + ns["tei"] + "sourceDesc")
    if file_description is not None:
        bibl_struct = file_description.find(".//" + ns["tei"] + "biblStruct")
        if bibl_struct is not None:
            dois = bibl_struct.findall(".//" + ns["tei"] + "idno[@type='DOI']")
            for res in dois:
                if res.text is not None:
                    doi = res.text
    return doi


def get_record_from_pdf_tei(filepath: Path) -> dict:

    # Note: we have more control and transparency over the consolidation
    # if we do it in the colrev_core process
    header_data = {"consolidateHeader": "0"}

    r = requests.post(
        GROBID_URL + "/api/processHeaderDocument",
        files=dict(input=open(filepath, "rb")),
        data=header_data,
    )

    status = r.status_code
    if status != 200:
        print(f"error: {r.text}")
        record = {
            "ENTRYTYPE": "misc",
            "error": "GROBID-Extraction failed",
            "error-msg": r.text,
        }

    if status == 200:
        root = etree.fromstring(r.text.encode("utf-8"))
        # print(etree.tostring(root, pretty_print=True).decode("utf-8"))
        record = {
            "ENTRYTYPE": "article",
            "title": get_paper_title(root),
            "author": get_paper_authors(root),
            "journal": get_paper_journal(root),
            "year": get_paper_year(root),
            "volume": get_paper_journal_volume(root),
            "number": get_paper_journal_issue(root),
            "pages": get_paper_journal_pages(root),
            "doi": get_paper_doi(root),
        }

    for k, v in record.items():
        if "file" != k:
            record[k] = v.replace("}", "").replace("{", "")
        else:
            print(f"problem in filename: {k}")

    return record


def get_bibliography(root):

    tei_bib_db = []

    bibliographies = root.iter(ns["tei"] + "listBibl")
    for bibliography in bibliographies:
        for reference in bibliography:

            ref_rec = {
                "ID": get_reference_bibliography_id(reference),
                "tei_id": get_reference_bibliography_tei_id(reference),
                "author": get_reference_author_string(reference),
                "title": get_reference_title_string(reference),
                "year": get_reference_year_string(reference),
                "journal": get_reference_journal_string(reference),
                "volume": get_reference_volume_string(reference),
                "number": get_reference_number_string(reference),
                "pages": get_reference_page_string(reference),
            }
            ref_rec = {k: v for k, v in ref_rec.items() if v is not None}
            # print(ref_rec)
            tei_bib_db.append(ref_rec)

    return tei_bib_db


def mark_references(root, records):
    from colrev_core.review_manager import RecordState
    from colrev_core import dedupe

    tei_records = get_bibliography(root)
    for record in tei_records:
        if "title" not in record:
            continue

        max_sim = 0.9
        max_sim_record = {}
        for local_record in records:
            if local_record["status"] not in [
                RecordState.rev_included,
                RecordState.rev_synthesized,
            ]:
                continue
            rec_sim = dedupe.get_record_similarity(record.copy(), local_record.copy())
            if rec_sim > max_sim:
                max_sim_record = local_record
                max_sim = rec_sim
        if len(max_sim_record) == 0:
            continue

        # Record found: mark in tei
        bibliography = root.find(".//" + ns["tei"] + "listBibl")
        # mark reference in bibliography
        for ref in bibliography:
            if ref.get(ns["w3"] + "id") == record["tei_id"]:
                ref.set("ID", max_sim_record["ID"])
        # mark reference in in-text citations
        for reference in root.iter(ns["tei"] + "ref"):
            if "target" in reference.keys():
                if reference.get("target") == f"#{record['tei_id']}":
                    reference.set("ID", max_sim_record["ID"])

        # if settings file available: dedupe_io match agains records
    return root


# (individual) bibliography-reference elements  ----------------------------


def get_reference_bibliography_id(reference):
    if "ID" in reference.attrib:
        return reference.attrib["ID"]
    else:
        return ""


def get_reference_bibliography_tei_id(reference):
    return reference.attrib[ns["w3"] + "id"]


def get_reference_author_string(reference):
    author_list = []
    if reference.find(ns["tei"] + "analytic") is not None:
        authors_node = reference.find(ns["tei"] + "analytic")
    elif reference.find(ns["tei"] + "monogr") is not None:
        authors_node = reference.find(ns["tei"] + "monogr")

    for author_node in authors_node.iterfind(ns["tei"] + "author"):

        authorname = get_author_name_from_node(author_node)

        if ", " != authorname and "" != authorname:
            author_list.append(authorname)

    author_string = " and ".join(author_list)

    author_string = (
        author_string.replace("\n", " ")
        .replace("\r", "")
        .replace("•", "")
        .replace("+", "")
        .replace("Dipl.", "")
        .replace("Prof.", "")
        .replace("Dr.", "")
        .replace("&apos", "'")
        .replace("❚", "")
        .replace("~", "")
        .replace("®", "")
        .replace("|", "")
    )

    # TODO: deduplicate
    if author_string is None:
        author_string = "NA"
    if "" == author_string.replace(" ", "").replace(",", "").replace(";", ""):
        author_string = "NA"
    return author_string


def get_reference_title_string(reference):
    title_string = ""
    if reference.find(ns["tei"] + "analytic") is not None:
        title = reference.find(ns["tei"] + "analytic").find(ns["tei"] + "title")
    elif reference.find(ns["tei"] + "monogr") is not None:
        title = reference.find(ns["tei"] + "monogr").find(ns["tei"] + "title")
    if title is None:
        title_string = "NA"
    else:
        title_string = title.text
    return title_string


def get_reference_year_string(reference):
    year_string = ""
    if reference.find(ns["tei"] + "monogr") is not None:
        year = (
            reference.find(ns["tei"] + "monogr")
            .find(ns["tei"] + "imprint")
            .find(ns["tei"] + "date")
        )
    elif reference.find(ns["tei"] + "analytic") is not None:
        year = (
            reference.find(ns["tei"] + "analytic")
            .find(ns["tei"] + "imprint")
            .find(ns["tei"] + "date")
        )

    if year is not None:
        for name, value in sorted(year.items()):
            if name == "when":
                year_string = value
            else:
                year_string = "NA"
    else:
        year_string = "NA"
    return year_string


def get_reference_page_string(reference):
    page_string = ""

    if reference.find(ns["tei"] + "monogr") is not None:
        page_list = (
            reference.find(ns["tei"] + "monogr")
            .find(ns["tei"] + "imprint")
            .findall(ns["tei"] + "biblScope[@unit='page']")
        )
    elif reference.find(ns["tei"] + "analytic") is not None:
        page_list = (
            reference.find(ns["tei"] + "analytic")
            .find(ns["tei"] + "imprint")
            .findall(ns["tei"] + "biblScope[@unit='page']")
        )

    for page in page_list:
        if page is not None:
            for name, value in sorted(page.items()):
                if name == "from":
                    page_string += value
                if name == "to":
                    page_string += "--" + value
        else:
            page_string = "NA"

    return page_string


def get_reference_number_string(reference):
    number_string = ""

    if reference.find(ns["tei"] + "monogr") is not None:
        number_list = (
            reference.find(ns["tei"] + "monogr")
            .find(ns["tei"] + "imprint")
            .findall(ns["tei"] + "biblScope[@unit='issue']")
        )
    elif reference.find(ns["tei"] + "analytic") is not None:
        number_list = (
            reference.find(ns["tei"] + "analytic")
            .find(ns["tei"] + "imprint")
            .findall(ns["tei"] + "biblScope[@unit='issue']")
        )

    for number in number_list:
        if number is not None:
            number_string = number.text
        else:
            number_string = "NA"

    return number_string


def get_reference_volume_string(reference):
    volume_string = ""

    if reference.find(ns["tei"] + "monogr") is not None:
        volume_list = (
            reference.find(ns["tei"] + "monogr")
            .find(ns["tei"] + "imprint")
            .findall(ns["tei"] + "biblScope[@unit='volume']")
        )
    elif reference.find(ns["tei"] + "analytic") is not None:
        volume_list = (
            reference.find(ns["tei"] + "analytic")
            .find(ns["tei"] + "imprint")
            .findall(ns["tei"] + "biblScope[@unit='volume']")
        )

    for volume in volume_list:
        if volume is not None:
            volume_string = volume.text
        else:
            volume_string = "NA"

    return volume_string


def get_reference_journal_string(reference):
    journal_title = ""
    if reference.find(ns["tei"] + "monogr") is not None:
        journal_title = (
            reference.find(ns["tei"] + "monogr").find(ns["tei"] + "title").text
        )
    if journal_title is None:
        journal_title = ""
    return journal_title