"""Stage repository documentation before delegating packaging to setuptools."""

from functools import wraps
from pathlib import Path
import shutil

from setuptools import build_meta


def _stage_documents():
    build_root = Path(__file__).resolve().parent
    repository = build_root.parent
    staged = build_root / "_release_docs"
    # An extracted sdist already contains these files and has no repository docs.
    if (repository / "root" / "_build_backend.py").resolve() == Path(__file__).resolve():
        documents = repository / "docs"
        license_file = repository / "LICENSE.md"
        if not (documents / "README.md").is_file() or not license_file.is_file():
            raise RuntimeError("Repository docs/README.md and LICENSE.md are required")
        for source in documents.rglob("*.md"):
            target = staged / "docs" / source.relative_to(documents)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(source), str(target))
        shutil.copyfile(str(license_file), str(staged / "LICENSE.md"))
    for required in (staged / "docs" / "README.md", staged / "LICENSE.md"):
        if not required.is_file():
            raise RuntimeError("Missing packaged document: {}".format(required))


def __getattr__(name):
    if name not in {
        "build_wheel", "build_sdist", "build_editable",
        "get_requires_for_build_wheel", "get_requires_for_build_sdist",
        "get_requires_for_build_editable", "prepare_metadata_for_build_wheel",
        "prepare_metadata_for_build_editable",
    }:
        raise AttributeError(name)
    hook = getattr(build_meta, name)

    @wraps(hook)
    def staged_hook(*args, **kwargs):
        _stage_documents()
        return hook(*args, **kwargs)

    return staged_hook
