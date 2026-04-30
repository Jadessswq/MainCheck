"""Валидация структуры расширения LibreOffice (.oxt)."""
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CLIENT = ROOT / "Клиент"
EXT_DIR = CLIENT / "AI_Suggester"
OXT = CLIENT / "AI_Suggester.oxt"


def _parse(p: Path) -> ET.Element:
    return ET.parse(p).getroot()


def test_description_version():
    root = _parse(EXT_DIR / "description.xml")
    version = root.find("{http://openoffice.org/extensions/description/2006}version")
    assert version is not None
    assert version.get("value") == "1.5.1"


def test_manifest_lists_library_and_xcu():
    root = _parse(EXT_DIR / "META-INF" / "manifest.xml")
    ns = "{urn:oasis:names:tc:opendocument:xmlns:manifest:1.0}"
    paths = {e.get(f"{ns}full-path") for e in root.findall(f"{ns}file-entry")}
    assert "ai_macro/" in paths
    assert "Addons.xcu" in paths


def test_script_xlb_lists_modules():
    root = _parse(EXT_DIR / "ai_macro" / "script.xlb")
    ns = "{http://openoffice.org/2000/library}"
    names = {e.get("library:name") or e.get(f"{ns}name") for e in root.findall(f"{ns}element")}
    assert {"Main", "Settings", "Health"}.issubset(names)


@pytest.mark.parametrize("name", ["Main.xba", "Settings.xba", "Health.xba"])
def test_basic_modules_are_parseable(name):
    p = EXT_DIR / "ai_macro" / name
    assert p.exists(), f"Отсутствует {p}"
    # XML корректный (несмотря на CDATA)
    ET.parse(p)
    body = p.read_text(encoding="utf-8")
    # Обёртка CDATA присутствует (защита от & в Basic-коде)
    assert "<![CDATA[" in body
    assert "]]>" in body


def test_addons_xcu_has_single_user_toolbar_entry():
    """
    У сотрудника на панели — ровно одна кнопка «AI: Улучшить текст» (m001).
    Диагностический Health.AICheckServer намеренно не вынесен на панель:
    сотрудник не должен видеть/менять URL сервера.
    """
    root = _parse(EXT_DIR / "Addons.xcu")
    ns = "{http://openoffice.org/2001/registry}"
    nodes = root.iter("node")
    names = {n.get(f"{ns}name") for n in nodes}
    assert "m001" in names  # AISuggestSelection — единственная кнопка работника
    assert "m002" not in names  # AICheckServer вынесен в меню макросов


def test_oxt_artifact_can_be_rebuilt(tmp_path):
    """Собираем .oxt из Клиент/AI_Suggester/ и проверяем, что архив валидный."""
    out = tmp_path / "AI_Suggester.oxt"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in EXT_DIR.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(EXT_DIR).as_posix())
    assert out.exists()
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        for expected in (
            "description.xml",
            "Addons.xcu",
            "META-INF/manifest.xml",
            "ai_macro/Main.xba",
            "ai_macro/Settings.xba",
            "ai_macro/Health.xba",
            "ai_macro/script.xlb",
            "ai_macro/dialog.xlb",
        ):
            assert expected in names, f"В .oxt нет {expected}"


def test_main_xba_uses_settings_module():
    body = (EXT_DIR / "ai_macro" / "Main.xba").read_text(encoding="utf-8")
    assert "Settings.GetServerList()" in body
    assert "Settings.GetUseTrackChanges()" in body
    assert "ApplyCorrection" in body
    assert "RecordChanges" in body
    # HTTP-status-code проверка
    assert "-w" in body and "http_code" in body


def test_committed_oxt_is_installable():
    """Собранный артефакт в корне должен быть валидным zip-архивом LibreOffice."""
    if not OXT.exists():
        pytest.skip("Клиент/AI_Suggester.oxt ещё не пересобран — пропускаем")
    with zipfile.ZipFile(OXT) as z:
        names = z.namelist()
    assert "description.xml" in names
    assert "META-INF/manifest.xml" in names
