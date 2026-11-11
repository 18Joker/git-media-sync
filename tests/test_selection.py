from downloader.core import FileEntry, build_tree, selected_entries


def test_selected_entries_returns_checked_files():
    es = [
        FileEntry("a/x.png", "x.png", 1, "f1", "pending"),
        FileEntry("a/y.png", "y.png", 1, "f2", "same"),
    ]
    roots = build_tree(es)
    assert [e.relpath for e in selected_entries(roots, {"a/x.png"})] == ["a/x.png"]


def test_selected_entries_empty():
    es = [FileEntry("z.png", "z.png", 1, "f1", "pending")]
    assert selected_entries(build_tree(es), set()) == []


def test_selected_entries_follows_tree_order():
    es = [
        FileEntry("b.png", "b.png", 1, "f1", "pending"),
        FileEntry("a/x.png", "x.png", 1, "f2", "pending"),
    ]
    roots = build_tree(es)
    got = selected_entries(roots, {"a/x.png", "b.png"})
    assert [e.relpath for e in got] == ["a/x.png", "b.png"]