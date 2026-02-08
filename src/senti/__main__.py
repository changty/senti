"""Entry point: python -m senti"""

import asyncio
import sys


def main() -> None:
    from senti.app import create_app

    async def _run() -> None:
        app = await create_app()
        async with app:
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            # Run until interrupted
            stop_event = asyncio.Event()
            try:
                await stop_event.wait()
            except (KeyboardInterrupt, SystemExit):
                pass
            finally:
                await app.updater.stop()
                await app.stop()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nShutting down.")
        sys.exit(0)


if __name__ == "__main__":
    main()
