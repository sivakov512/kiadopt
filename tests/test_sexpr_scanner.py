import pytest

from kiadopt import sexpr


def test_reads_strings_with_parentheses_quotes_and_escapes() -> None:
    text = '(a "x (y) \\"z\\"" "back\\\\slash" "line\\nbreak" bare)'

    root = sexpr.parse(text)

    values = [item.value for item in root.items]
    assert values == ["a", 'x (y) "z"', "back\\slash", "line\nbreak", "bare"]


def test_remembers_where_atoms_and_nodes_are() -> None:
    text = '(lib (name "Local") (uri "${KIPRJMOD}/x"))'

    root = sexpr.parse(text)

    name = root.value("name")
    uri = root.child("uri")
    assert name is not None
    assert uri is not None
    assert text[name.start : name.end] == '"Local"'
    assert text[uri.start : uri.end] == '(uri "${KIPRJMOD}/x")'
    assert (root.start, root.end) == (0, len(text))


def test_finds_property_values() -> None:
    root = sexpr.parse(
        '(symbol "R" (property "Footprint" "R:0603" (at 0 0)) (property "Value" "10k"))'
    )

    footprint = root.property("Footprint")
    assert footprint is not None
    assert footprint.value == "R:0603"
    assert root.property("Datasheet") is None


def test_quoted_value_reads_back_the_same() -> None:
    value = 'a "b" \\ c\nd'

    atom = sexpr.parse(f"(x {sexpr.quote(value)})").atom(1)

    assert atom is not None
    assert atom.value == value


def test_replaces_values_and_keeps_everything_else() -> None:
    text = '(a\n\t(b "old")   \r\n\t(c "keep")\n)'
    old = sexpr.parse(text).value("b")
    assert old is not None

    edited = sexpr.replace_values(text, [(old, 'new "one"')])

    assert edited == '(a\n\t(b "new \\"one\\"")   \r\n\t(c "keep")\n)'


def test_refuses_overlapping_edits() -> None:
    with pytest.raises(ValueError, match="overlapping"):
        sexpr.splice("abcdef", [(0, 3, "x"), (2, 4, "y")])


def test_tokens_do_not_depend_on_formatting() -> None:
    assert sexpr.tokens('(a\n\t"b" c)') == sexpr.tokens('(a "b"   c)')
    assert sexpr.tokens('(a "b")') != sexpr.tokens('(a "c")')


def test_starts_new_line_when_appending_to_one_line_list() -> None:
    text = "(t (a))"

    assert sexpr.append_lines(text, sexpr.parse(text), "\t(b)\n") == "(t (a)\n\t(b)\n)"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("(a", "unexpected end"),
        ("(a))", "unbalanced"),
        ("(a) (b)", "more than one"),
        ("x (a)", "outside"),
        ('(a "open)', "unexpected"),
        ("", "unexpected end"),
    ],
)
def test_raises_on_malformed_text(text: str, message: str) -> None:
    with pytest.raises(sexpr.ParseError, match=message):
        sexpr.parse(text)
