"""Tests for sanitize_voice_text() — markdown/URL stripping before TTS.

Covers the three failure modes observed in MCP call transcripts:
  1. Bare URLs spoken aloud over the phone.
  2. Markdown links [Product Name](https://…) read verbatim.
  3. Bullet points, bold/italic markers, and heading hashes cluttering speech.

Also verifies TOKEN-mode chunk safety: each test case is realistic for the
chunk sizes that arrive when the LLM streams token-by-token.
"""

import pytest

from botelier.voice.speech_normalize import normalize_for_speech, sanitize_voice_text


# ---------------------------------------------------------------------------
# sanitize_voice_text — unit tests
# ---------------------------------------------------------------------------


class TestUrlStripping:
    def test_bare_https_url_removed(self):
        assert sanitize_voice_text("Visit https://example.com for details.") == "Visit for details."

    def test_bare_http_url_removed(self):
        assert sanitize_voice_text("See http://store.com/products here.") == "See here."

    def test_url_with_path_and_query_removed(self):
        result = sanitize_voice_text(
            "https://davidprotein.com/products/triple-chocolate-pint"
        )
        assert result == ""

    def test_long_checkout_url_removed(self):
        long_url = (
            "https://davidprotein.com/cart/c/hWNGNNTp4rvLgRVdM7Wg5Eu1"
            "?key=bB4FJPWcgQ76AmB5OK7BYun5sLwZLfQvzszlnT_q8eJmlbK9wxajpdq"
        )
        result = sanitize_voice_text(f"Complete your purchase here: {long_url}")
        assert "https" not in result
        assert "davidprotein" not in result
        assert "Complete your purchase here:" in result

    def test_no_url_unchanged(self):
        text = "The bar has 20 grams of protein."
        assert sanitize_voice_text(text) == text


class TestMarkdownLinkStripping:
    """Markdown links [text](url) — as seen in product listing responses."""

    def test_full_markdown_link_reduces_to_display_text(self):
        result = sanitize_voice_text("[Double Chocolate](https://davidprotein.com/products/double-chocolate)")
        # URL gone, brackets gone — only the display text remains (with possible extra space)
        assert "Double Chocolate" in result
        assert "https" not in result
        assert "[" not in result
        assert "]" not in result

    def test_markdown_link_inline(self):
        result = sanitize_voice_text(
            "Check out [Triple Chocolate Pint](https://davidprotein.com/products/triple-chocolate-pint) today."
        )
        assert "Triple Chocolate Pint" in result
        assert "https" not in result
        assert "today" in result

    # TOKEN-mode chunk simulation: the markdown link arrives split at spaces.
    def test_token_chunk_open_bracket(self):
        """'[Triple' — bracket prefix arrives alone."""
        assert sanitize_voice_text("[Triple") == "Triple"

    def test_token_chunk_closing_bracket_with_url(self):
        """'Pint](https://…)' — closing bracket + URL arrives as one token."""
        result = sanitize_voice_text("Pint](https://davidprotein.com/products/triple-chocolate-pint)")
        assert result == "Pint"

    def test_token_chunk_middle_word_unchanged(self):
        """Interior words of a link name pass through untouched."""
        assert sanitize_voice_text("Chocolate") == "Chocolate"

    def test_standalone_brackets_removed(self):
        assert sanitize_voice_text("[Note]") == "Note"
        assert sanitize_voice_text("[") == ""
        assert sanitize_voice_text("]") == ""


class TestMarkdownFormattingStripping:
    def test_bold_double_asterisk(self):
        result = sanitize_voice_text("**Bold text** here")
        assert "Bold text" in result
        assert "*" not in result

    def test_bold_single_asterisk(self):
        result = sanitize_voice_text("*italic* word")
        assert "italic" in result
        assert "*" not in result

    def test_heading_hash_stripped(self):
        result = sanitize_voice_text("## Product Options")
        assert "Product Options" in result
        assert "#" not in result

    def test_unordered_bullet_dash_stripped(self):
        result = sanitize_voice_text("- Double Chocolate bar")
        assert "Double Chocolate bar" in result
        assert result.startswith("Double")

    def test_unordered_bullet_asterisk_stripped(self):
        result = sanitize_voice_text("* Peanut Butter bar")
        assert "Peanut Butter bar" in result
        assert result.startswith("Peanut")

    def test_backtick_code_markers_stripped(self):
        result = sanitize_voice_text("`checkout`")
        assert result == "checkout"

    def test_plain_text_unchanged(self):
        text = "We have the Double Chocolate bar and the Peanut Butter Chocolate."
        assert sanitize_voice_text(text) == text


class TestRealWorldTranscriptChunks:
    """Replicate exact chunks seen in the David's Protein call transcripts."""

    def test_product_list_entry(self):
        """Full product list line as it appeared in the 5:39 PM call."""
        line = "1. [Triple Chocolate Pint](https://davidprotein.com/products/triple-chocolate-pint) - This flavor features rich chocolate."
        result = sanitize_voice_text(line)
        assert "Triple Chocolate Pint" in result
        assert "This flavor features rich chocolate" in result
        assert "https" not in result
        assert "[" not in result

    def test_checkout_url_with_long_key(self):
        """The full checkout URL from the 5:32 PM call — must vanish entirely."""
        url = (
            "https://davidprotein.com/cart/c/hWNGNNTp4rvLgRVdM7Wg5Eu1"
            "?key=bB4FJPWcgQ76AmB5OK7BYun5sLwZLfQvzszlnT_q8eJmlbK9wxajpdq"
            "YqZraWWMX6dRkzHEtB_JrvN_-Yhfcr8e3kAuRi9XuhRQO54MaEBE5nDR4lm"
            "w2anvIC"
        )
        result = sanitize_voice_text(f"Complete your purchase here: {url}")
        assert "https" not in result
        assert "davidprotein" not in result

    def test_bulleted_product_list(self):
        """Dash-bulleted list chunk from the 5:32 PM call."""
        chunk = "- [Double Chocolate Protein Bar](https://davidprotein.com/products/double-chocolate): 20g protein, 150 calories."
        result = sanitize_voice_text(chunk)
        assert "Double Chocolate Protein Bar" in result
        assert "20g protein" in result
        assert "https" not in result
        assert result[0].isalpha() or result[0].isdigit(), "Should not start with a bullet char"


# ---------------------------------------------------------------------------
# normalize_for_speech integration — sanitization runs first
# ---------------------------------------------------------------------------


class TestNormalizeIntegration:
    """Verify that sanitize_voice_text fires inside normalize_for_speech."""

    def test_url_stripped_before_numeric_expansion(self):
        """URL digits must not trigger number-to-word conversion."""
        result = normalize_for_speech("Buy at https://shop.com/products/1234")
        assert "https" not in result
        assert "shop" not in result
        # The word "Buy at" should survive
        assert "Buy at" in result

    def test_markdown_link_stripped_then_normalized(self):
        """Link display text containing a 3+ digit number gets normalized correctly.
        normalize_for_speech intentionally leaves 1-2 digit numbers alone (TTS
        reads them fine); use a 3-digit number to exercise expansion."""
        result = normalize_for_speech("[Top 300 picks](https://example.com/top300)")
        assert "https" not in result
        # "300" in "Top 300 picks" should be expanded to "three hundred"
        assert "three hundred" in result

    def test_plain_numeric_text_still_normalized(self):
        """Sanitization must not break regular numeric normalization."""
        assert normalize_for_speech("3rd place") == "third place"
        assert normalize_for_speech("1,500 calories") == "one thousand five hundred calories"
