import json

import pytest

from downloader.manifest import (
    Manifest, ManifestError, ManifestFile, group_by_folder, parse_manifest,
)

VALID = '{"version": 1, "generated_at": "2026-11-12T21:30:00", "files": [{"path": "assets/a.png", "size": 3}]}'


def test_parse_valid():
    m = parse_manifest(VALID)
    assert m == Manifest(1, "2026-11-12T21:30:00", [ManifestFile("assets/a.png", 3)])


def test_parse_generated_at_optional():
    assert parse_manifest('{"version": 1, "files": []}').generated_at == ""


@pytest.mark.parametrize("text", ["{ bad", "[]", '{"version": 2, "files": []}',
                                  '{"version": 1}', '{"version": 1, "files": {}}'])
def test_parse_bad_shape_raises(text):
    with pytest.raises(ManifestError):
        parse_manifest(text)


@pytest.mark.parametrize("path", ["../a.png", "a/../b.png", "/a.png", "a\\b.png",
                                  "C:/a.png", "", "a//b.png", "a/./b.png", 'a<b.png', "a:b.png"])
def test_parse_bad_path_raises(path):
    with pytest.raises(ManifestError):
        parse_manifest('{"version": 1, "files": [{"path": %s, "size": 1}]}' % json.dumps(path))


@pytest.mark.parametrize("size", [-1, "3", 1.5, True, None])
def test_parse_bad_size_raises(size):
    with pytest.raises(ManifestError):
        parse_manifest('{"version": 1, "files": [{"path": "a.png", "size": %s}]}' % json.dumps(size))


def test_parse_duplicate_path_raises():
    with pytest.raises(ManifestError):
        parse_manifest('{"version": 1, "files": [{"path": "a.png", "size": 1}, {"path": "a.png", "size": 2}]}')


def test_group_by_folder():
    files = [ManifestFile("a.png", 1), ManifestFile("d/b.png", 2), ManifestFile("d/e/c.png", 3)]
    assert group_by_folder(files) == {
        "": [files[0]], "d": [files[1]], "d/e": [files[2]],
    }