import argparse
import sys

from .config import load_config
from .slack_bot import start


def main(argv=None):
    parser = argparse.ArgumentParser(description="Aira — your personal AI assistant (Jerry-style)")
    parser.add_argument("--cli", action="store_true", help="run as a terminal chat instead of Slack")
    parser.add_argument("--web", action="store_true", help="run the local browser frontend (no accounts needed)")
    parser.add_argument("--once", metavar="TASK", help="run a single task headlessly and exit")
    parser.add_argument("--voice", action="store_true", help="run hands-free voice mode (\"Hey Aira\")")
    parser.add_argument("--popup", action="store_true", help="run the Siri-style overlay popup (hotkey: Option+Space)")
    parser.add_argument("--assistant", action="store_true", help="run Aira full-time: popup + text + \"Hey Aira\" all in one")
    parser.add_argument("--automate", metavar="TYPE", help="run one content automation and exit: carousel | linkedin | briefing | blog")
    parser.add_argument("--count", type=int, default=5, help="number of blog posts to generate (blog automation only)")
    args = parser.parse_args(argv)

    cfg = load_config()
    if args.automate:
        from .automation import run_automation
        from pprint import pprint
        res = run_automation(cfg, args.automate, n=args.count) if args.automate == "blog" else run_automation(cfg, args.automate)
        if not res.get("ok"):
            print(f"Aira automation '{args.automate}' failed:", res.get("error"))
            return 1
        print(f"Aira automation '{args.automate}' done.")
        pprint({k: v for k, v in res.items() if k != "ok"})
        return 0
    if args.assistant:
        from .assistant import run_assistant
        run_assistant(cfg)
        return 0
    if args.popup:
        from .webui import start_web
        import os
        import subprocess
        import time

        app = os.path.expanduser("~/aira/AiraPopup.app")
        if not os.path.isdir(app):
            print("AiraPopup.app not built yet — run ~/aira/build_popup.sh first.")
            return 1
        print("Aira popup mode — web API on http://127.0.0.1:8756, popup hotkey Option+Space")
        subprocess.Popen(["open", app])
        start_web(cfg, open_browser=False)
        return 0
    if args.once:
        from .cli import run as cli_run
        cli_run(cfg, once=args.once)
        return 0
    if args.web:
        from .webui import start_web
        start_web(cfg)
        return 0
    if args.cli:
        from .cli import run as cli_run
        cli_run(cfg)
        return 0
    if args.voice:
        from .voice import run_voice
        run_voice(cfg)
        return 0

    bot_token = cfg.slack_bot_token()
    app_token = cfg.slack_app_token()
    if not bot_token or not app_token:
        print("Missing Slack tokens. Set these environment variables (see README):")
        print("  export AIRA_SLACK_BOT_TOKEN=xoxb-...")
        print("  export AIRA_SLACK_APP_TOKEN=xapp-...")
        print("Or use the no-account web frontend:  ./venv/bin/python -m aira.main --web")
        print("Or test first with:  ./venv/bin/python -m aira.main --cli")
        return 1

    from .brain import Brain
    from .cli import CliSession
    from .email_watcher import EmailWatcher
    from .scheduler import Scheduler
    from .slack_bot import SlackSession

    def brain_factory(executor):
        if executor is None:
            from .executor import ToolExecutor
            executor = ToolExecutor(CliSession(), cfg)
        return Brain(cfg, executor)

    app, holder, handler = start(cfg, brain_factory=brain_factory)

    if cfg.get("email", {}).get("enabled"):
        watcher = EmailWatcher(cfg, brain_factory, post_client=app.client)
        app._aira_ack_handler = watcher.ack   # wire the Slack 'Got it' button
        import threading
        threading.Thread(target=watcher.run, daemon=True).start()

    scheduler = Scheduler(cfg, brain_factory, session_factory=lambda channel: SlackSession(app.client, channel, None))
    import threading
    threading.Thread(target=scheduler.run, daemon=True).start()

    print("Aira is live on Slack. Press Ctrl+C to stop.")
    try:
        handler.start()
    except KeyboardInterrupt:
        handler.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
