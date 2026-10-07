"""Read-only diagram/UI checks against the isolated guitar_preview_server catalog."""
from playwright.sync_api import sync_playwright

JOB = "d0a3f98491a64544a5a86c568dc9ffef"


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/google/chrome/chrome", headless=True,
                                    args=["--no-sandbox"])
        for name, width in (("desktop", 1365), ("mobile", 390), ("small-mobile", 320)):
            context = browser.new_context(viewport={"width": width, "height": 900},
                                         is_mobile=width < 500, has_touch=width < 500)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto("http://127.0.0.1:8790/login")
            page.locator('[name="username"]').fill("browser-test")
            page.locator('[name="password"]').fill("local-browser-test-password")
            page.locator('button[type="submit"]').click()
            page.locator(f'[data-job="{JOB}"]').click()
            page.locator("#timeline .chord-block").first.wait_for()
            index = page.evaluate("chords().findIndex(segment => ChordLabVoicings.positions(segment.chord).length > 0)")
            page.locator(f'#timeline [data-segment="{index}"]').click()
            page.locator(".chord-chart").wait_for()
            assert page.locator(".chord-string").count() == 6
            # Deterministic examples do not save or alter the analysis.
            page.evaluate('renderVoicing("C")')
            assert page.locator(".chord-nut").count() == 1
            assert page.locator(".chord-open-muted").count() == 3
            buttons = page.locator("#voicingPositions button")
            assert buttons.count() > 1
            assert buttons.first.get_attribute("aria-pressed") == "true"
            page.get_by_role("button", name="第 8 把位", exact=True).click()
            assert page.locator(".chord-nut").count() == 0
            assert page.locator(".chord-barre").count() == 1
            assert page.locator(".chord-fret-number").first.text_content() == "8"
            assert page.locator('.chord-chart').get_attribute("aria-label").startswith("6 弦第 8 格")
            assert page.evaluate('document.activeElement.textContent') == "第 8 把位"
            page.evaluate('renderVoicing("Am")')
            assert buttons.first.get_attribute("aria-pressed") == "true"
            assert page.locator("#selectedChord").inner_text() == "Am"
            # Real capo event must redraw the currently selected timeline chord.
            page.locator(f'#timeline [data-segment="{index}"]').click()
            page.locator("#capoSelect").select_option("2")
            assert "原和弦" in page.locator("#selectedChord").inner_text()
            assert "相對 Capo 2" in page.locator("#voicingNotes").inner_text()
            assert page.locator('.chord-chart').is_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            assert page.evaluate('''() => {
                const b = document.querySelector(".chord-chart").getBoundingClientRect();
                return b.left >= 0 && b.right <= innerWidth;
            }''')
            page.locator("#capoSelect").select_option("0")
            page.evaluate('renderVoicing("F")')
            page.locator(".chord-chart").scroll_into_view_if_needed()
            page.screenshot(path=f"/tmp/chordlab-chord-diagram-{name}.png")
            page.evaluate('renderVoicing("N")')
            assert page.locator("#voicingPositions").is_hidden()
            assert page.locator(".chord-chart").count() == 0
            page.evaluate('renderVoicing(null)')
            assert page.locator("#selectedChord").inner_text() == "選擇一個和弦"
            assert not errors, errors
            print(name, "diagram/positions/focus/capo/viewport passed", flush=True)
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
