from laya_browser import is_natural, rank


class FakeAgent:  # picks the option containing "submit", else the first
    def predict(self, state, qs):
        pick = lambda c: next((o for o in c if "submit" in o), c[0])
        return {"answers": {k: {"choice": pick(q["criteria"]), "confidence": 0.9} for k, q in qs.items()}}


def test_is_natural():
    for sel in ["@e1", "#id", ".btn", "button", "text=Go", "input[name=q]", "//a", "500", "a > b"]:
        assert not is_natural(sel), sel
    for nl in ["the login link", "Sign in", "post a story", "~button"]:
        assert is_natural(nl), nl


def test_rank():
    els = [(f"e{i}", "link", f"story {i}") for i in range(100)]
    els += [("e200", "cell", "login"), ("e201", "link", "login"), ("e202", "link", "submit")]
    assert rank(FakeAgent(), "log in", els)["ref"] == "e201"  # lexical fast path, cell skipped
    assert rank(FakeAgent(), "post a story", els)["ref"] == "e202"  # tournament across 4 chunks
    radios = [("e1", "radio", " Medium"), ("e2", "radio", " Large")]
    assert rank(FakeAgent(), "large pizza", radios)["ref"] == "e2"  # word-subset fast path


if __name__ == "__main__":
    test_is_natural(); test_rank(); print("ok")
