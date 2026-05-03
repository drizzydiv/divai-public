#!/usr/bin/env python3
"""divAI onboarding wizard — first-run personalized setup"""

import sys
import os
import subprocess
import json
import threading

CLI_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE  = os.path.join(CLI_DIR, "div_config.json")
LITELLM_FILE = os.path.join(CLI_DIR, "litellm_config.yaml")

try:
    from textual.app import App, ComposeResult
    from textual.screen import Screen
    from textual.widget import Widget
    from textual.widgets import Button, Input, Static, Switch, Footer
    from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
    from textual.reactive import reactive
    from textual import on
except ImportError:
    print("\n[divAI] Installing onboarding UI (textual)...")
    subprocess.run([sys.executable, "-m", "pip", "install", "textual>=0.40.0", "--quiet"])
    from textual.app import App, ComposeResult
    from textual.screen import Screen
    from textual.widget import Widget
    from textual.widgets import Button, Input, Static, Switch, Footer
    from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
    from textual.reactive import reactive
    from textual import on


# ── Data ─────────────────────────────────────────────────────────────────────

LOGO = """\
   ██████╗ ██╗██╗   ██╗ █████╗ ██╗
   ██╔══██╗██║██║   ██║██╔══██╗██║
   ██║  ██║██║██║   ██║███████║██║
   ██║  ██║██║╚██╗ ██╔╝██╔══██║██║
   ██████╔╝██║ ╚████╔╝ ██║  ██║██║
   ╚═════╝ ╚═╝  ╚═══╝  ╚═╝  ╚═╝╚═╝"""

TIERS = [
    {
        "id": "free",
        "title": "Free",
        "models": "Groq Llama 3.3 70B",
        "desc": "Fast chat + voice.\n100% free, no credit card.",
        "price": "$0 / month",
        "keys": ["groq"],
    },
    {
        "id": "balanced",
        "title": "Balanced",
        "models": "Groq + DeepSeek Reasoner",
        "desc": "Free chat & voice plus deep\nreasoning for tough problems.",
        "price": "~$1–5 / month",
        "keys": ["groq", "deepseek"],
    },
    {
        "id": "full",
        "title": "Full Power",
        "models": "Groq · GitHub · DeepSeek · OpenAI",
        "desc": "All four providers.\nPick the best tool for any task.",
        "price": "Pay-per-use",
        "keys": ["groq", "github", "deepseek", "openai"],
    },
]

KEY_META = {
    "groq": {
        "name": "Groq",
        "hint": "/talk (Llama 3.3) + voice transcription",
        "url": "https://console.groq.com/keys",
        "placeholder": "gsk_...",
        "prefix": "gsk_",
        "test_url": "https://api.groq.com/openai/v1/models",
    },
    "github": {
        "name": "GitHub PAT  (free GPT-4o)",
        "hint": "/code mode — free via GitHub Models",
        "url": "https://github.com/settings/tokens",
        "placeholder": "github_pat_...",
        "prefix": "github_pat_",
        "test_url": None,
    },
    "deepseek": {
        "name": "DeepSeek",
        "hint": "/brain mode — deep reasoning",
        "url": "https://platform.deepseek.com/api_keys",
        "placeholder": "sk-...",
        "prefix": "sk-",
        "test_url": None,
    },
    "openai": {
        "name": "OpenAI",
        "hint": "/divfull mode — GPT-4o",
        "url": "https://platform.openai.com/api-keys",
        "placeholder": "sk-proj-...",
        "prefix": "sk-",
        "test_url": None,
    },
}


# ── CSS ───────────────────────────────────────────────────────────────────────

APP_CSS = """
Screen {
    background: #050d1a;
    color: #c0cce0;
}

#welcome-box {
    align: center middle;
    padding: 2 4;
}

.logo {
    color: #00aaff;
    text-align: center;
    padding: 1 0;
    width: 100%;
}

.heading {
    color: #00aaff;
    text-style: bold;
    text-align: center;
    padding: 1 0;
    width: 100%;
}

.subtext {
    color: #556688;
    text-align: center;
    padding: 0 4;
    width: 100%;
}

/* ── Budget cards ── */
#tier-row {
    height: auto;
    padding: 1 2;
}

TierCard {
    width: 1fr;
    border: round #1a2e42;
    padding: 1 2;
    margin: 0 1;
    height: auto;
}

TierCard:hover {
    border: round #00aaff;
}

.card-title { color: #00aaff; text-style: bold; }
.card-models { color: #8899bb; text-style: italic; }
.card-price { color: #44cc88; text-style: bold; }
.card-desc { color: #778899; }

/* ── Key input cards ── */
KeyCard {
    border: round #1a2e42;
    padding: 1 2;
    margin: 0 0 1 0;
    height: auto;
}

.key-name { color: #00aaff; text-style: bold; }
.key-hint { color: #556688; }
.key-link { color: #3399cc; }

.key-status {
    width: 16;
    content-align: center middle;
    padding: 0 0 0 1;
}

/* ── Integration cards ── */
.int-card {
    border: round #1a2e42;
    padding: 1 2;
    margin: 0 0 1 0;
    height: auto;
}

.int-title {
    color: #00aaff;
    text-style: bold;
    width: 1fr;
}

.hidden { display: none; }

/* ── Done screen ── */
.check-ok   { color: #44cc88; padding: 0 4; }
.check-skip { color: #334455; padding: 0 4; }

.countdown {
    color: #00aaff;
    text-style: bold;
    text-align: center;
    width: 100%;
    padding: 1 0;
}

/* ── Navigation ── */
.nav-row {
    align: right middle;
    height: 3;
    padding: 0 2;
}

/* ── Buttons ── */
Button {
    border: tall #1a3a5a;
    background: #050d1a;
    color: #00aaff;
    margin: 0 1;
}

Button:hover {
    background: #001a2e;
    border: tall #00aaff;
}

Button.-primary {
    background: #00aaff;
    color: #000000;
    text-style: bold;
    border: tall #0088cc;
}

Button.-primary:hover {
    background: #33bbff;
}

/* ── Inputs ── */
Input {
    border: round #1a2e42;
    background: #030810;
    color: #c0cce0;
}

Input:focus {
    border: round #00aaff;
}
"""


# ── Screens ───────────────────────────────────────────────────────────────────

class WelcomeScreen(Screen):
    BINDINGS = [("escape", "quit_app", "Quit"), ("q", "quit_app", "Quit")]

    def compose(self) -> ComposeResult:
        yield Container(
            Static(LOGO, classes="logo"),
            Static("[bold #00aaff]Welcome to divAI[/]", classes="heading"),
            Static("Your personal AI assistant — chat, voice, and smart integrations.", classes="subtext"),
            Static(""),
            Static(
                "This takes about [bold]2 minutes[/bold].\n"
                "We'll help you pick models and link your API keys.",
                classes="subtext",
            ),
            Static(""),
            Button("Let's go  →", variant="primary", id="start"),
            id="welcome-box",
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            self.app.push_screen(BudgetScreen())

    def action_quit_app(self) -> None:
        self.app.exit(0)


class TierCard(Widget):
    def __init__(self, tier: dict, **kwargs):
        super().__init__(**kwargs)
        self.tier = tier

    def compose(self) -> ComposeResult:
        yield Static(f"[bold]{self.tier['title']}[/bold]", classes="card-title")
        yield Static(self.tier["models"], classes="card-models")
        yield Static("")
        yield Static(self.tier["desc"], classes="card-desc")
        yield Static("")
        yield Static(self.tier["price"], classes="card-price")
        yield Static("")
        yield Button(f"Choose {self.tier['title']}  →", id=f"tier_{self.tier['id']}")


class BudgetScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Static("[bold #00aaff]Pick your plan[/]", classes="heading")
        yield Static("You can always add or change models later with /key.", classes="subtext")
        yield Static("")
        yield Horizontal(
            *[TierCard(tier) for tier in TIERS],
            id="tier-row",
        )
        yield Horizontal(
            Button("← Back", id="back"),
            classes="nav-row",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id and event.button.id.startswith("tier_"):
            self.app.tier_id = event.button.id.removeprefix("tier_")
            self.app.push_screen(KeysScreen())


class KeyCard(Widget):
    def __init__(self, provider_id: str, **kwargs):
        super().__init__(**kwargs)
        self.provider_id = provider_id
        self.meta = KEY_META[provider_id]

    def compose(self) -> ComposeResult:
        url = self.meta["url"]
        yield Static(
            f"[bold #00aaff]{self.meta['name']}[/]  [#556688]{self.meta['hint']}[/]",
            classes="key-name",
        )
        yield Static(
            f"[link={url}]→ Get your key at {url}[/link]",
            classes="key-link",
        )
        yield Horizontal(
            Input(
                placeholder=self.meta["placeholder"],
                password=True,
                id=f"key_{self.provider_id}",
            ),
            Button("Test", id=f"test_{self.provider_id}"),
            Static("", id=f"status_{self.provider_id}", classes="key-status"),
        )

    @on(Input.Changed)
    def _on_key_changed(self, event: Input.Changed) -> None:
        if event.input.id != f"key_{self.provider_id}":
            return
        status = self.query_one(f"#status_{self.provider_id}", Static)
        val = event.value.strip()
        if not val:
            status.update("")
        elif val.startswith(self.meta["prefix"]):
            status.update("[#44cc88]✓[/]")
        else:
            status.update("[#ff5555]✗ bad format[/]")

    @on(Button.Pressed)
    def _on_test(self, event: Button.Pressed) -> None:
        if event.button.id != f"test_{self.provider_id}":
            return
        event.stop()
        key = self.query_one(f"#key_{self.provider_id}", Input).value.strip()
        status = self.query_one(f"#status_{self.provider_id}", Static)
        test_url = self.meta.get("test_url")

        if not key:
            status.update("[#ff5555]no key entered[/]")
            return

        if not test_url:
            status.update(
                "[#44cc88]✓ looks valid[/]"
                if key.startswith(self.meta["prefix"])
                else "[#ff5555]✗ bad format[/]"
            )
            return

        status.update("[#888888]testing...[/]")

        def _do_test():
            try:
                import requests
                r = requests.get(
                    test_url,
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=5,
                )
                ok = r.status_code == 200
            except Exception:
                ok = False
            self.app.call_from_thread(
                lambda: status.update("[#44cc88]✓ valid[/]" if ok else "[#ff5555]✗ invalid[/]")
            )

        threading.Thread(target=_do_test, daemon=True).start()


class KeysScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        tier = next(t for t in TIERS if t["id"] == self.app.tier_id)
        yield ScrollableContainer(
            Static("[bold #00aaff]API Keys[/]", classes="heading"),
            Static(
                f"Setting up: [#00aaff]{tier['title']}[/] tier  ·  "
                f"paste keys below, then click [bold]Test[/bold] to verify.",
                classes="subtext",
            ),
            Static(""),
            *[KeyCard(pid) for pid in tier["keys"]],
        )
        yield Horizontal(
            Button("← Back", id="back"),
            Button("Next  →", variant="primary", id="next"),
            classes="nav-row",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "next":
            tier = next(t for t in TIERS if t["id"] == self.app.tier_id)
            self.app.collected_keys = {
                pid: self.query_one(f"#key_{pid}", Input).value.strip()
                for pid in tier["keys"]
            }
            self.app.push_screen(IntegrationsScreen())


class IntegrationsScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]
    _canvas_on = reactive(False)
    _vault_on = reactive(False)

    def compose(self) -> ComposeResult:
        yield ScrollableContainer(
            Static("[bold #00aaff]Optional Integrations[/]", classes="heading"),
            Static(
                "Both are optional — you can set these up later with /canvas and /vault.",
                classes="subtext",
            ),
            Static(""),
            # Canvas
            Container(
                Horizontal(
                    Static(
                        "[bold]Canvas LMS[/]  [#556688]assignments & grades from your school[/]",
                        classes="int-title",
                    ),
                    Switch(id="canvas-toggle"),
                ),
                Container(
                    Static(
                        "[link=https://community.canvaslms.com/t5/Student-Guide/"
                        "How-do-I-manage-API-access-tokens-as-a-student/ta-p/432355]"
                        "→ How to get your Canvas token[/link]",
                        classes="key-link",
                    ),
                    Input(placeholder="https://yourschool.instructure.com", id="canvas-url"),
                    Input(placeholder="Paste your Canvas access token", password=True, id="canvas-token"),
                    id="canvas-fields",
                    classes="hidden",
                ),
                classes="int-card",
            ),
            # Vault
            Container(
                Horizontal(
                    Static(
                        "[bold]Obsidian Vault[/]  [#556688]notes & session logs[/]",
                        classes="int-title",
                    ),
                    Switch(id="vault-toggle"),
                ),
                Container(
                    Input(placeholder=r"C:\Users\you\Documents\MyVault", id="vault-path"),
                    id="vault-fields",
                    classes="hidden",
                ),
                classes="int-card",
            ),
        )
        yield Horizontal(
            Button("← Back", id="back"),
            Button("Finish  →", variant="primary", id="next"),
            classes="nav-row",
        )

    @on(Switch.Changed, "#canvas-toggle")
    def _toggle_canvas(self, event: Switch.Changed) -> None:
        self._canvas_on = event.value
        fields = self.query_one("#canvas-fields")
        fields.remove_class("hidden") if event.value else fields.add_class("hidden")

    @on(Switch.Changed, "#vault-toggle")
    def _toggle_vault(self, event: Switch.Changed) -> None:
        self._vault_on = event.value
        fields = self.query_one("#vault-fields")
        fields.remove_class("hidden") if event.value else fields.add_class("hidden")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "next":
            if self._canvas_on:
                self.app.canvas_url = self.query_one("#canvas-url", Input).value.strip().rstrip("/")
                self.app.canvas_token = self.query_one("#canvas-token", Input).value.strip()
            else:
                self.app.canvas_url = ""
                self.app.canvas_token = ""
            if self._vault_on:
                self.app.vault_path = (
                    self.query_one("#vault-path", Input).value.strip().strip('"').strip("'")
                )
            else:
                self.app.vault_path = ""
            self.app.push_screen(DoneScreen())


class DoneScreen(Screen):
    countdown = reactive(3)

    def on_mount(self) -> None:
        self._timer = self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        self.countdown -= 1
        if self.countdown <= 0:
            self._timer.stop()
            _write_config(self.app)
            self.app.exit(0)

    def watch_countdown(self, value: int) -> None:
        try:
            self.query_one("#countdown", Static).update(
                f"[bold #00aaff]Starting divAI in {value}s...[/]"
                if value > 0
                else "[bold #44cc88]Launching![/]"
            )
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        app = self.app
        tier = next(t for t in TIERS if t["id"] == app.tier_id)

        items = []
        for pid in tier["keys"]:
            key = app.collected_keys.get(pid, "")
            if key:
                items.append(Static(f"[#44cc88]✓[/]  {KEY_META[pid]['name']}", classes="check-ok"))
            else:
                items.append(
                    Static(f"[#334455]○[/]  {KEY_META[pid]['name']} — skipped", classes="check-skip")
                )
        if app.canvas_url:
            items.append(Static("[#44cc88]✓[/]  Canvas LMS", classes="check-ok"))
        else:
            items.append(Static("[#334455]○[/]  Canvas — skipped", classes="check-skip"))
        if app.vault_path:
            items.append(Static("[#44cc88]✓[/]  Obsidian Vault", classes="check-ok"))
        else:
            items.append(Static("[#334455]○[/]  Vault — skipped", classes="check-skip"))

        yield Container(
            Static("[bold #00aaff]You're all set![/]", classes="heading"),
            Static(""),
            *items,
            Static(""),
            Static("[#556688]Config saved → div_config.json[/]", classes="subtext"),
            Static(""),
            Static("[bold #00aaff]Starting divAI in 3s...[/]", id="countdown", classes="countdown"),
        )


# ── Config writer ─────────────────────────────────────────────────────────────

def _write_config(app: "OnboardApp") -> None:
    keys = app.collected_keys
    groq_key = keys.get("groq", "")

    models = {
        "talk":  {"model": "groq/llama-3.3-70b-versatile",  "key": groq_key},
        "code":  {"model": "github/gpt-4o",                  "key": keys.get("github", groq_key)},
        "brain": {"model": "deepseek/deepseek-reasoner",     "key": keys.get("deepseek", "")},
        "full":  {"model": "openai/gpt-4o",                  "key": keys.get("openai", "")},
    }

    config = {
        "models": models,
        "vault": app.vault_path,
        "canvas_url": app.canvas_url,
        "canvas_token": app.canvas_token,
        "last_briefing": "",
    }

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

    # Write litellm_config.yaml (for the divAI CLI proxy)
    lines = ["model_list:"]
    if groq_key:
        lines += [
            '  - model_name: "divtalk"',
            '    litellm_params:',
            '      model: "groq/llama-3.1-8b-instant"',
            f'      api_key: "{groq_key}"',
            "",
        ]
    deepseek_key = keys.get("deepseek", "")
    if deepseek_key:
        lines += [
            '  - model_name: "divbrain"',
            '    litellm_params:',
            '      model: "deepseek/deepseek-reasoner"',
            f'      api_key: "{deepseek_key}"',
            "",
        ]
    lines += ["litellm_settings:", "  drop_params: true", ""]

    with open(LITELLM_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ── App ───────────────────────────────────────────────────────────────────────

class OnboardApp(App):
    CSS = APP_CSS
    TITLE = "divAI Setup"

    def on_mount(self) -> None:
        self.tier_id = "free"
        self.collected_keys = {}
        self.canvas_url = ""
        self.canvas_token = ""
        self.vault_path = ""
        self.push_screen(WelcomeScreen())


if __name__ == "__main__":
    OnboardApp().run()
