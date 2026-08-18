
from __future__ import annotations

import os
import sys
from pathlib import Path


# ============================================================
# Пути
# ============================================================

APP_DIR = Path(__file__).resolve().parent
UI_DIR = APP_DIR / "ui"
INDEX = UI_DIR / "index.html"


# Делаем корень проекта доступным для локальных импортов.
PROJECT_ROOT = APP_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# Окружение
# ============================================================

def setup_environment() -> bool:
    """
    Минимальная настройка окружения.

    ВАЖНО:
    - не отключаем compositing;
    - не отключаем аппаратное ускорение;
    - не трогаем DMABUF без необходимости;
    - не заставляем WebKit работать через software rendering.
    """

    # Явно используем GTK backend.
    os.environ.setdefault("PYWEBVIEW_GUI", "gtk")

    debug = os.environ.get(
        "ZAPRETGUI_DEBUG",
        "",
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    return debug


# ============================================================
# Проверки
# ============================================================

def check_files() -> None:
    """Проверяет наличие UI-файлов."""

    if not UI_DIR.exists():
        print(
            f"[zapretgui] ОШИБКА: папка UI не найдена:\n"
            f"  {UI_DIR}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1)

    if not INDEX.exists():
        print(
            f"[zapretgui] ОШИБКА: index.html не найден:\n"
            f"  {INDEX}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1)


def load_dependencies():
    """
    Импортирует зависимости после базовых проверок.

    Это позволяет получить нормальную диагностику вместо
    загадочного traceback при обычном запуске.
    """

    try:
        import webview
    except ImportError as exc:
        print(
            "[zapretgui] Не установлен pywebview.\n"
            "Установи его в виртуальном окружении.",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1) from exc

    try:
        from app.core.api import Api
    except ImportError as exc:
        print(
            f"[zapretgui] Не удалось импортировать API: {exc}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1) from exc

    return webview, Api


# ============================================================
# DEV shortcuts
# ============================================================

def install_dev_shortcuts(window) -> None:
    """
    Устанавливает только в debug-режиме:

        F5
        Ctrl+R
        F12
    """

    try:
        from gi.repository import Gdk
    except Exception as exc:
        print(
            f"[zapretgui] GTK shortcuts недоступны: {exc}",
            flush=True,
        )
        return

    native = getattr(window, "native", None)

    if native is None:
        print(
            "[zapretgui] native GTK window недоступно",
            flush=True,
        )
        return

    def on_key_press(_widget, event):
        key = event.keyval
        modifiers = event.get_state()

        ctrl = bool(
            modifiers & Gdk.ModifierType.CONTROL_MASK
        )

        # ----------------------------------------------------
        # F5 / Ctrl+R
        # ----------------------------------------------------

        if (
            key == Gdk.KEY_F5
            or (
                ctrl
                and key in (
                    Gdk.KEY_r,
                    Gdk.KEY_R,
                )
            )
        ):
            try:
                window.evaluate_js(
                    "window.location.reload();"
                )

                print(
                    "[zapretgui] reload",
                    flush=True,
                )

            except Exception as exc:
                print(
                    f"[zapretgui] reload error: {exc}",
                    flush=True,
                )

            return True

        # ----------------------------------------------------
        # F12
        # ----------------------------------------------------

        if key == Gdk.KEY_F12:
            try:
                # pywebview использует BrowserView внутри GTK.
                from webview.platforms.gtk import BrowserView

                browser = BrowserView.instances.get(
                    window.uid
                )

                if browser is None:
                    raise RuntimeError(
                        "BrowserView не найден"
                    )

                inspector = (
                    browser.webview.get_inspector()
                )

                inspector.show()

                print(
                    "[zapretgui] inspector",
                    flush=True,
                )

            except Exception as exc:
                print(
                    f"[zapretgui] inspector error: {exc}",
                    flush=True,
                )

            return True

        return False

    try:
        native.connect(
            "key-press-event",
            on_key_press,
        )

        print(
            "[zapretgui] DEV shortcuts: "
            "F5 / Ctrl+R / F12",
            flush=True,
        )

    except Exception as exc:
        print(
            f"[zapretgui] shortcuts error: {exc}",
            flush=True,
        )


# ============================================================
# Main
# ============================================================

def main() -> None:
    debug = setup_environment()

    # --------------------------------------------------------
    # Базовые проверки
    # --------------------------------------------------------

    check_files()

    # --------------------------------------------------------
    # Зависимости
    # --------------------------------------------------------

    webview, Api = load_dependencies()

    # --------------------------------------------------------
    # Backend
    # --------------------------------------------------------

    try:
        api = Api()
    except Exception as exc:
        print(
            f"[zapretgui] Ошибка инициализации API: {exc}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1) from exc

    # --------------------------------------------------------
    # URL
    # --------------------------------------------------------

    url = INDEX.as_uri()

    print(
        "[zapretgui] "
        f"app={APP_DIR}",
        flush=True,
    )

    print(
        "[zapretgui] "
        f"ui={INDEX}",
        flush=True,
    )

    print(
        "[zapretgui] "
        f"debug={'on' if debug else 'off'}",
        flush=True,
    )

    # --------------------------------------------------------
    # Окно
    # --------------------------------------------------------

    window = webview.create_window(
        title="ZapretGUI",
        url=url,
        js_api=api,

        width=960,
        height=640,

        min_size=(640, 480),

        resizable=True,
        fullscreen=False,
        frameless=False,

        background_color="#111111",

        # Не включаем дополнительные эффекты самого окна.
        transparent=False,
        vibrancy=False,
    )

    # --------------------------------------------------------
    # loaded
    # --------------------------------------------------------

    def on_loaded() -> None:
        print(
            "[zapretgui] UI загружен",
            flush=True,
        )

        if debug:
            install_dev_shortcuts(window)

    # --------------------------------------------------------
    # closed
    # --------------------------------------------------------

    def on_closed() -> None:
        print(
            "[zapretgui] окно закрыто",
            flush=True,
        )

        try:
            shutdown = getattr(
                api,
                "shutdown",
                None,
            )

            if callable(shutdown):
                shutdown()

        except Exception as exc:
            print(
                f"[zapretgui] shutdown error: {exc}",
                file=sys.stderr,
                flush=True,
            )

    window.events.loaded += on_loaded
    window.events.closed += on_closed

    # --------------------------------------------------------
    # GTK/WebKit
    # --------------------------------------------------------

    print(
        "[zapretgui] запуск GTK/WebKit",
        flush=True,
    )

    try:
        webview.start(
            gui="gtk",

            # В обычном запуске debug полностью отключён.
            debug=debug,

            # Никаких дополнительных HTTP-серверов:
            # file:// нам уже достаточно.
            http_server=False,

            # Для приложения без авторизации/сессий
            # приватный режим проще и не создаёт
            # постоянное хранилище без необходимости.
            private_mode=True,
        )

    except KeyboardInterrupt:
        print(
            "[zapretgui] остановлено пользователем",
            flush=True,
        )

    except Exception as exc:
        print(
            f"[zapretgui] ошибка WebKit/GTK: {exc}",
            file=sys.stderr,
            flush=True,
        )

        raise SystemExit(1) from exc

    finally:
        # На случай, если GTK завершился без события closed.
        try:
            shutdown = getattr(
                api,
                "shutdown",
                None,
            )

            if callable(shutdown):
                shutdown()

        except Exception:
            pass


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    main()
