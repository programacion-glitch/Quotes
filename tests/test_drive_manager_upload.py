"""Unit de DriveManager: matching de carpeta de cliente (robusto a USDOT/US DOT/
DOT), reuso/creación de subcarpeta de quotes, y naming de la indicación.
Service de Drive falso (no toca red)."""
import re
from datetime import datetime

from modules.drive_manager import DriveManager


class _Exec:
    def __init__(self, val):
        self._val = val

    def execute(self):
        return self._val


class _FakeFiles:
    def __init__(self, tree):
        self.tree = tree            # {parent_id: [{id,name,mimeType}, ...]}
        self.created = []

    def list(self, q="", **kw):
        m = re.search(r"'([^']+)' in parents", q or "")
        parent = m.group(1) if m else None
        items = list(self.tree.get(parent, []))
        if "vnd.google-apps.folder" in (q or ""):
            items = [i for i in items if i["mimeType"].endswith("folder")]
        mc = re.search(r"name contains '([^']+)'", q or "")
        if mc:
            items = [i for i in items if mc.group(1) in i["name"]]
        return _Exec({"files": [{"id": i["id"], "name": i["name"]} for i in items]})

    def create(self, body=None, media_body=None, **kw):
        fid = f"created_{len(self.created) + 1}"
        self.created.append({"id": fid, "name": body.get("name"),
                             "parents": body.get("parents"),
                             "media": media_body})
        parent = (body.get("parents") or [None])[0]
        self.tree.setdefault(parent, []).append({
            "id": fid, "name": body.get("name"),
            "mimeType": body.get("mimeType", "application/octet-stream"),
        })
        return _Exec({"id": fid})


class _FakeService:
    def __init__(self, tree):
        self._files = _FakeFiles(tree)

    def files(self):
        return self._files


def _folder(fid, name):
    return {"id": fid, "name": name,
            "mimeType": "application/vnd.google-apps.folder"}


def _dm(tree, parent="PARENT"):
    dm = DriveManager.__new__(DriveManager)   # saltea __init__/auth
    dm.service = _FakeService(tree)
    dm.main_folder_id = parent
    dm.auth_mode = "user_oauth"
    return dm


def test_match_by_usdot_variants():
    tree = {"PARENT": [
        _folder("c1", "1 FMB FREIGHT LLC USDOT 2468083"),
        _folder("c2", "PSR TRUCKINGDELIVERY LLC US DOT 3540105"),
        _folder("c3", "R SIERRA TRUCK LLC  DOT 4214632"),
    ]}
    dm = _dm(tree)
    assert dm._find_client_folder("PSR TRUCKINGDELIVERY LLC", "3540105") == "c2"
    assert dm._find_client_folder("R SIERRA TRUCK LLC", "4214632") == "c3"
    assert dm._find_client_folder("1 FMB FREIGHT LLC", "2468083") == "c1"


def test_match_fallback_by_business_name_when_no_dot():
    tree = {"PARENT": [
        _folder("c1", "1 FMB FREIGHT LLC USDOT 2468083"),
        _folder("c3", "R SIERRA TRUCK LLC  DOT 4214632"),
    ]}
    dm = _dm(tree)
    # 'DOT NA' / sin número -> match por nombre
    assert dm._find_client_folder("R SIERRA TRUCK LLC", "NA") == "c3"


def test_create_client_folder_when_missing():
    tree = {"PARENT": []}
    dm = _dm(tree)
    fid = dm._find_or_create_client_folder("NEW CO LLC", "9998887")
    assert fid is not None
    created = dm.service.files().created
    assert any(c["name"] == "NEW CO LLC USDOT 9998887" for c in created)


def test_quotes_subfolder_reused_if_exists():
    tree = {"PARENT": [_folder("c1", "X LLC USDOT 1234567")],
            "c1": [_folder("q1", "2) QUotes")]}
    dm = _dm(tree)
    assert dm._find_or_create_quotes_subfolder("c1") == "q1"


def test_quotes_subfolder_created_if_missing():
    tree = {"PARENT": [_folder("c1", "X LLC USDOT 1234567")], "c1": []}
    dm = _dm(tree)
    qid = dm._find_or_create_quotes_subfolder("c1")
    created = dm.service.files().created
    assert any(c["name"] == "2) Quotes" and c["parents"] == ["c1"]
               for c in created)
    assert qid is not None


def test_upload_indication_naming_and_location(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    tree = {"PARENT": [_folder("c1", "1 FMB FREIGHT LLC USDOT 2468083")],
            "c1": [_folder("q1", "2) QUotes")], "q1": []}
    dm = _dm(tree)
    fid = dm.upload_quote_indication(
        "1 FMB FREIGHT LLC", "2468083", str(pdf),
        carrier="PROGRESSIVE", when=datetime(2026, 6, 25),
    )
    assert fid is not None and fid != "exists"
    created = dm.service.files().created
    up = [c for c in created if c["media"] is not None]
    assert len(up) == 1
    assert up[0]["name"] == "20260625 - Indications Progressive.pdf"
    assert up[0]["parents"] == ["q1"]


def test_upload_indication_skips_if_already_exists(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    tree = {
        "PARENT": [_folder("c1", "1 FMB FREIGHT LLC USDOT 2468083")],
        "c1": [_folder("q1", "2) QUotes")],
        "q1": [{"id": "f0", "name": "20260625 - Indications Progressive.pdf",
                "mimeType": "application/pdf"}],
    }
    dm = _dm(tree)
    res = dm.upload_quote_indication(
        "1 FMB FREIGHT LLC", "2468083", str(pdf),
        carrier="PROGRESSIVE", when=datetime(2026, 6, 25),
    )
    assert res == "exists"
