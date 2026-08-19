"""Offline unit tests for the editor-authored prose counter.

Locks the metric definition: exclude templates / <ref> / categories / tables;
include headings and image captions; keep plain text + link display text.
"""

import pytest

from services import editor_prose_counter as ep


def w(text, **kw):
    return ep.editor_prose_words(text, **kw)


def test_empty():
    assert w("") == 0
    assert w(None) == 0


def test_plain_prose():
    assert w("The cat sat on the mat.") == 6


def test_count_references():
    cr = ep.count_references
    assert cr("") == 0 and cr("No refs here.") == 0
    assert cr("Text.<ref>cite</ref> More.<ref name=\"a\">c2</ref>") == 2  # defined
    assert cr("Reuse.<ref name=\"a\" /> and <ref name=\"b\"/>") == 2      # self-closing
    assert cr("<references/>") == 0                                       # container, not a ref
    assert cr("<ref>one</ref>\n<references responsive />") == 1


def test_words_joined_by_punctuation_are_split():
    # editor omitted the space: "college(own" is two words, not one
    assert w("ਕਾਲਜ(ਆਪਣੇ") == 2
    assert w("college(own building)here") == 4  # college, own, building, here
    assert w("शिक्षा(अपने") == 2
    assert w("word।word") == 2               # Indic danda without space


def test_intraword_punctuation_stays_one_word():
    # contractions, compounds, acronyms, decimals must remain single words
    assert w("don't") == 1
    assert w("well-known") == 1
    assert w("U.S.A. and 3.14 here") == 4


def test_indic_matras_stay_attached():
    # combining vowel signs must not split the word
    assert w("ਸਿੱਖਿਆ ਦੇ ਖੇਤਰ ਵਿੱਚ") == 4


def test_malformed_heading_word_still_counts():
    # a broken heading "==X=" leaks "=X"; the word must still count, so fixing
    # the "=" (balancing the heading) does NOT change the word count.
    assert w("==ਹਵਾਲੇ=\nsome body prose here") == w("==ਹਵਾਲੇ==\nsome body prose here")
    assert w("==ਹਵਾਲੇ=") == 1        # "ਹਵਾਲੇ" counted despite the stray =
    # but an internal key=value (attribute residue) is still dropped
    assert w("Good prose here align=center more prose words") == 6


def test_wikilink_display_text_counts():
    assert w("The [[Felis catus|domestic cat]] is small.") == 5  # "domestic cat" kept


def test_external_link_display_text_counts():
    assert w("See [https://example.com the example site] now.") == 5


def test_bold_italic_text_counts():
    assert w("A '''bold''' and ''italic'' word.") == 5


# --- exclusions ------------------------------------------------------------- #
def test_templates_excluded():
    assert w("{{Multiple issues|{{cleanup}}{{unreferenced}}}} Real prose here.") == 3


def test_infobox_excluded():
    assert w("{{Infobox animal|name=Cat|weight=4kg}}\nA cat is a pet.") == 5


def test_references_excluded():
    assert w("Cats are cute.<ref>{{cite web|title=Cats are great}}</ref> Yes.") == 4
    assert w('Text before<ref name="x" /> and after here.') == 5


def test_categories_excluded():
    assert w("Some prose here now. [[Category:Cats]] [[Category:Pets]]") == 4


def test_categories_excluded_localized():
    # Hindi category namespace name
    assert w("कुछ सामग्री यहाँ है [[श्रेणी:बिल्लियाँ]]",
             category_names=("श्रेणी", "Category")) == 4


def test_tables_excluded():
    assert w("Before text.\n{|\n! H\n|-\n| a || b\n|}\nAfter text now.") == 5


# --- inclusions ------------------------------------------------------------- #
def test_headings_included():
    assert w("== History ==\nThe cat was domesticated.") == 5  # History + 4


def test_image_caption_included_options_dropped():
    # caption kept; thumb/250px dropped; File title dropped
    assert w("[[File:cat.jpg|thumb|250px|A cute tabby cat]] Prose follows now.") == 7


def test_image_with_no_caption_contributes_nothing():
    assert w("[[File:cat.jpg|thumb|right|200px]] Only this prose counts here.") == 5


def test_image_alt_param_not_counted_as_caption():
    # alt= is a named param, not the visible caption
    assert w("[[File:x.jpg|thumb|alt=hidden alt text]] Visible prose only.") == 3


# --- custom tags / edge cases (from deep-drive testing) --------------------- #
def test_html_comment_excluded():
    assert w("Real text <!-- hidden comment words here --> and more.") == 4


def test_magic_words_excluded():
    assert w("__TOC__ __NOTOC__ Real prose words here.") == 4


def test_redirect_is_zero():
    assert w("#REDIRECT [[Some Target Page]]") == 0
    assert w("#redirect [[X]]") == 0


def test_interlanguage_link_excluded():
    assert w("Prose words here now. [[de:Katze]] [[fr:Chat]]") == 4


def test_namespace_link_with_display_text_kept():
    # a real namespace link (capitalised) keeps its display text
    assert w("See [[Help:Editing|editing help]] for tips.") == 5


def test_code_and_syntaxhighlight_excluded():
    assert w("Call <code>print(x)</code> to output.") == 3
    assert w("Example:\n<syntaxhighlight lang=py>\nprint(1)\n</syntaxhighlight>\nDone here.") == 3


def test_math_and_nowiki_excluded():
    assert w("Energy is <math>E=mc^2</math> a famous formula.") == 5
    assert w("Type <nowiki>{{template}}</nowiki> to show it.") == 4


def test_gallery_excluded():
    assert w("<gallery>\nFile:a.jpg|First caption\nFile:b.jpg|Second\n</gallery>") == 0


def test_blockquote_and_lists_included():
    assert w("<blockquote>To be or not to be</blockquote>") == 6
    assert w("* First item here\n* Second item here") == 6


def test_infobox_with_nested_template_and_ref_does_not_leak():
    # Regression: a regex <ref> strip used to unbalance the infobox braces so
    # mwparserfromhell mis-parsed it as text and leaked its param VALUES.
    wt = ("{{Infobox school\n| name = Ash Manor School\n"
          "| coordinates = {{coord|51.24|-0.72}}\n"
          "| motto = Aspire and Achieve<ref>{{cite web|title=Motto}}</ref>\n"
          "| head = Agnes Bailey}}\n"
          "Real prose sentence here now.")
    assert w(wt) == 5  # only "Real prose sentence here now."


def test_no_raw_markup_tokens_leak():
    # structural-char safety net: a standalone token containing raw markup
    # (| ]] = or a bare URL) is dropped, leaving the 6 real prose words.
    for junk in ("|", "|}", "||", "|-", "city]]", "align=center",
                 "http://example.com/x"):
        assert w(f"Good prose here {junk} more prose words") == 6
