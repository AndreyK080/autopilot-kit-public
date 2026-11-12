"""Запись файлов пользователя вне репозитория: с резервной копией."""
from datetime import datetime, timezone
from pathlib import Path
import shutil


def write_with_backup(path: Path, text: str) -> bool:
    """Пишет text в path. Если там другой файл — сначала копия path.bak-<UTC>. Возвращает True, если файл изменён."""
    path = Path(path)
    if path.exists():
        if path.read_text(encoding="utf-8") == text:
            return False
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(path, path.with_name(f"{path.name}.bak-{stamp}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return True
