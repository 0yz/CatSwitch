import os
import sys
import socket
import threading
import webview
import json
import logging
import time
import requests
from flask import Flask, request, jsonify
from catswitch.web_interface import initialize_app
from catswitch.settings import (
    load_window_position,
    save_window_position,
    load_always_on_top,
    save_always_on_top,
    load_home_compact_view,
    get_home_view_size,
    get_home_view_min_size,
    load_minimize_to_tray,
    load_autostart_with_windows,
    save_window_settings,
)
from catswitch.app_icons import (
    apply_app_window_icon,
    hide_app_window,
    show_app_window,
)
from catswitch.tray_icon import TrayIcon
from catswitch.paths import get_app_icon_path
from waitress import serve

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# Waitress warns whenever more than one request is queued; that's normal for
# brief bursts (tab loads, SSE + API calls) in this single-user desktop app.
logging.getLogger('waitress.queue').setLevel(logging.ERROR)
logger = logging.getLogger('catswitch.desktop_app')

# Fixed by Twitch Developer Console redirect URI (http://localhost:51111) — do not change.
LOCAL_SERVER_PORT = 51111
_SINGLE_INSTANCE_MUTEX_NAME = "Local\\CatSwitch_SingleInstance"
_instance_mutex = None
_instance_owned = False
_force_exit_scheduled = False

# Global variable for window reference
window = None


def schedule_force_process_exit(delay_sec: float = 2.0) -> None:
    """Guarantee the process dies after window teardown (Inno / WebView2 edge cases)."""
    global _force_exit_scheduled
    if _force_exit_scheduled:
        return
    _force_exit_scheduled = True

    def _force_exit():
        time.sleep(max(0.0, delay_sec))
        os._exit(0)

    threading.Thread(
        target=_force_exit, name="CatSwitchForceExit", daemon=True
    ).start()


def _local_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Return True if we can bind the local server port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # Do not use SO_REUSEADDR here — on Windows it can succeed while another
        # process is already listening, which hid the "already running" case.
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def _fail_port_in_use(port: int) -> None:
    """Exit with a clear message when the Twitch-fixed local port is unavailable."""
    message = (
        f"Port {port} is occupied — CatSwitch can't launch.\n\n"
        "Is an instance of CatSwitch already running?"
    )
    logger.error(message.replace("\n\n", " "))
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, "CatSwitch", 0x10)
    except Exception:
        print(message, file=sys.stderr)
    sys.exit(1)


def _activate_running_instance() -> bool:
    """Bring an already-running CatSwitch window to the foreground."""
    activated = False

    # Prefer asking the live local server (works when the window is hidden to tray).
    try:
        response = requests.post(
            f"http://127.0.0.1:{LOCAL_SERVER_PORT}/api/window-control",
            json={"action": "focus"},
            timeout=1.5,
        )
        if response.ok and (response.json() or {}).get("success"):
            activated = True
    except Exception:
        pass

    try:
        import win32api
        import win32con
        import win32gui
        import win32process

        hwnd = win32gui.FindWindow(None, "CatSwitch")
        if hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            try:
                foreground = win32gui.GetForegroundWindow()
                if foreground:
                    fg_thread, _fg_pid = win32process.GetWindowThreadProcessId(foreground)
                    cur_thread = win32api.GetCurrentThreadId()
                    if fg_thread != cur_thread:
                        win32process.AttachThreadInput(cur_thread, fg_thread, True)
                        try:
                            win32gui.BringWindowToTop(hwnd)
                            win32gui.SetForegroundWindow(hwnd)
                        finally:
                            win32process.AttachThreadInput(cur_thread, fg_thread, False)
                    else:
                        win32gui.SetForegroundWindow(hwnd)
                else:
                    win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            activated = True
    except Exception as exc:
        logger.debug("Win32 activate existing instance failed: %s", exc)

    return activated


def ensure_single_instance() -> bool:
    """Return True if this process should run; else activate the existing app and return False."""
    global _instance_mutex, _instance_owned

    if _instance_owned:
        return True

    try:
        import win32api
        import win32event
        import winerror
    except ImportError:
        logger.warning("win32 APIs unavailable — skipping single-instance guard")
        return True

    handle = win32event.CreateMutex(None, False, _SINGLE_INSTANCE_MUTEX_NAME)
    already_running = win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS
    if already_running:
        logger.info("CatSwitch is already running — activating existing window")
        if not _activate_running_instance():
            logger.warning("Could not activate existing CatSwitch window")
        try:
            win32api.CloseHandle(handle)
        except Exception:
            pass
        return False

    # Keep the mutex handle alive for the process lifetime.
    _instance_mutex = handle
    _instance_owned = True
    return True


def focus_window():
    """Bring the CatSwitch window to the foreground (and unhide from tray if needed)."""
    try:
        import win32gui
        import win32con
        import win32api
        import win32process

        try:
            show_app_window(window)
        except Exception:
            pass

        hwnd = None
        if window and hasattr(window, 'gui') and hasattr(window.gui, 'handle'):
            hwnd = window.gui.handle
        if not hwnd:
            hwnd = win32gui.FindWindow(None, 'CatSwitch')
        if not hwnd:
            return False

        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        try:
            foreground = win32gui.GetForegroundWindow()
            if foreground:
                fg_thread, _fg_pid = win32process.GetWindowThreadProcessId(foreground)
                cur_thread = win32api.GetCurrentThreadId()
                if fg_thread != cur_thread:
                    win32process.AttachThreadInput(cur_thread, fg_thread, True)
                    try:
                        win32gui.BringWindowToTop(hwnd)
                        win32gui.SetForegroundWindow(hwnd)
                    finally:
                        win32process.AttachThreadInput(cur_thread, fg_thread, False)
                else:
                    win32gui.SetForegroundWindow(hwnd)
            else:
                win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        return True
    except Exception as e:
        logger.error(f"Error focusing window: {e}", exc_info=True)
        return False


def get_window_position():
    """Get the current window position"""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        
        # Get window handle - different ways to try to get it
        hwnd = None
        
        # Method 1: Direct handle access
        if hasattr(window, 'gui') and hasattr(window.gui, 'handle'):
            hwnd = window.gui.handle
        
        # Method 2: For WinForms implementation
        if not hwnd and hasattr(window, 'gui') and hasattr(window.gui, 'main_window'):
            if hasattr(window.gui.main_window, 'Handle'):
                hwnd = window.gui.main_window.Handle.ToInt64()
        
        # Method 3: Get foreground window (fallback)
        if not hwnd:
            hwnd = user32.GetForegroundWindow()
        
        if hwnd:
            # Get current position
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            return {"x": rect.left, "y": rect.top, "width": rect.right - rect.left, "height": rect.bottom - rect.top}
        else:
            logger.error("Could not get window handle for position")
            return None
    except Exception as e:
        logger.error(f"Error getting window position: {e}", exc_info=True)
        return None

def set_window_position(x, y):
    """Set the window position to absolute coordinates"""
    logger.info(f"Set window position called: x={x}, y={y}")
    try:
        # Get current position
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        
        # Get window handle - different ways to try to get it
        hwnd = None
        
        # Method 1: Direct handle access
        if hasattr(window, 'gui') and hasattr(window.gui, 'handle'):
            hwnd = window.gui.handle
            logger.debug(f"Using window.gui.handle: {hwnd}")
        
        # Method 2: For WinForms implementation
        if not hwnd and hasattr(window, 'gui') and hasattr(window.gui, 'main_window'):
            if hasattr(window.gui.main_window, 'Handle'):
                hwnd = window.gui.main_window.Handle.ToInt64()
                logger.debug(f"Using WinForms handle: {hwnd}")
        
        # Method 3: Get foreground window (fallback)
        if not hwnd:
            hwnd = user32.GetForegroundWindow()
            logger.debug(f"Using foreground window handle: {hwnd}")
        
        if hwnd:
            # Define constants
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            
            # Use integers for coordinates
            x_pos = int(x)
            y_pos = int(y)
            
            # Move window with absolute positioning
            result = user32.SetWindowPos(
                hwnd, 
                0,  # hWndInsertAfter - no change in z-order
                x_pos, y_pos,  # New position
                0, 0,  # No size change
                SWP_NOSIZE | SWP_NOZORDER  # Flags
            )
            
            if result:
                logger.debug(f"Window moved to absolute position: x={x_pos}, y={y_pos}")
                return True
            else:
                error = ctypes.WinError()
                logger.error(f"SetWindowPos failed: {error}")
                return False
        else:
            logger.error("Could not get window handle")
            return False
    except Exception as e:
        logger.error(f"Error setting window position: {e}", exc_info=True)
        return False

def move_window(delta_x, delta_y):
    """Move the window by the specified delta coordinates"""
    logger.info(f"Move window called: dx={delta_x}, dy={delta_y}")
    try:
        # Get current position
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        
        # Get window handle - different ways to try to get it
        hwnd = None
        
        # Method 1: Direct handle access
        if hasattr(window, 'gui') and hasattr(window.gui, 'handle'):
            hwnd = window.gui.handle
            logger.debug(f"Using window.gui.handle: {hwnd}")
        
        # Method 2: For WinForms implementation
        if not hwnd and hasattr(window, 'gui') and hasattr(window.gui, 'main_window'):
            if hasattr(window.gui.main_window, 'Handle'):
                hwnd = window.gui.main_window.Handle.ToInt64()
                logger.debug(f"Using WinForms handle: {hwnd}")
        
        # Method 3: Get foreground window (fallback)
        if not hwnd:
            hwnd = user32.GetForegroundWindow()
            logger.debug(f"Using foreground window handle: {hwnd}")
        
        if hwnd:
            # Define constants
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            
            # Get current position
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            logger.debug(f"Current position: left={rect.left}, top={rect.top}")
            
            # Calculate new position
            x = rect.left + int(delta_x)
            y = rect.top + int(delta_y)
            
            # Move window
            result = user32.SetWindowPos(
                hwnd, 
                0,  # hWndInsertAfter - no change in z-order
                x, y,  # New position
                0, 0,  # No size change
                SWP_NOSIZE | SWP_NOZORDER  # Flags
            )
            
            if result:
                logger.debug(f"Window moved to: x={x}, y={y}")
                return True
            else:
                error = ctypes.WinError()
                logger.error(f"SetWindowPos failed: {error}")
                return False
        else:
            logger.error("Could not get window handle")
            return False
    except Exception as e:
        logger.error(f"Error moving window: {e}", exc_info=True)
        return False

class DesktopApp:
    def __init__(self, client_id, oauth_token, start_minimized=False):
        self.client_id = client_id
        self.oauth_token = oauth_token
        self.flask_app = None
        self.window = None
        self.tray_icon = None
        self.port = LOCAL_SERVER_PORT  # Local UI server port — fixed
        self.token_check_interval = 15 * 60  # Check token every 15 minutes
        self.token_valid = True  # Assume token is valid at start
        self.start_minimized = bool(start_minimized)
        self._applied_start_minimized = False

    def restore_from_tray(self):
        """Restore the main window after a tray icon click."""
        show_app_window(window)
        focus_window()

    def quit_app(self):
        """Quit the application from the tray menu."""
        global window
        schedule_force_process_exit(2.0)
        if window:
            window.destroy()
            return
        os._exit(0)

    def sync_tray_icon(self, enabled=None):
        """Start or stop the tray icon based on the minimize-to-tray setting."""
        if enabled is None:
            enabled = load_minimize_to_tray()

        if enabled:
            if self.tray_icon is None:
                icon_path = get_app_icon_path()
                self.tray_icon = TrayIcon(
                    icon_path,
                    tooltip="CatSwitch",
                    on_show=self.restore_from_tray,
                    on_quit=self.quit_app,
                )
            self.tray_icon.show()
            return

        if self.tray_icon is not None:
            self.tray_icon.stop()
            self.tray_icon = None

    def minimize_or_hide_window(self):
        """Minimize normally, or hide to tray when that setting is enabled."""
        if load_minimize_to_tray():
            if hide_app_window(window):
                self.sync_tray_icon(True)
                logger.info("Window hidden to tray")
                return True
            logger.error("Failed to hide window to tray")
            return False

        if window:
            window.minimize()
            logger.info("Window minimized")
            return True
        return False

    def initialize_flask(self):
        """Initialize the Flask app in a way compatible with PyWebView"""
        # Initialize the Flask app
        self.flask_app = initialize_app(self.client_id, self.oauth_token)
        
        # Configure for production
        self.flask_app.config['ENV'] = 'production'
        self.flask_app.config['DEBUG'] = False
        self.flask_app.config['TESTING'] = False
        
        # Add API routes for window control
        @self.flask_app.route('/api/window-control', methods=['POST'])
        def window_control():
            """Handle window control API requests"""
            from flask import request, jsonify
            global window
            
            data = request.json
            action = data.get('action')
            result = {"success": False}
            
            if action == 'move':
                delta_x = data.get('deltaX', 0)
                delta_y = data.get('deltaY', 0)
                result["success"] = move_window(delta_x, delta_y)
            
            elif action == 'position':
                x = data.get('x', 0)
                y = data.get('y', 0)
                result["success"] = set_window_position(x, y)
            
            elif action == 'minimize':
                try:
                    result["success"] = self.minimize_or_hide_window()
                except Exception as e:
                    logger.error(f"Error minimizing window: {e}")
                    result["error"] = str(e)
            
            elif action == 'close':
                try:
                    schedule_force_process_exit(2.0)
                    if window:
                        window.destroy()
                        result["success"] = True
                        logger.info("Window closed via API")
                except Exception as e:
                    logger.error(f"Error closing window: {e}")
                    try:
                        schedule_force_process_exit(0.5)
                        result["success"] = True
                    except Exception as e2:
                        result["error"] = str(e2)

            elif action == 'focus':
                try:
                    show_app_window(window)
                except Exception:
                    pass
                result["success"] = focus_window()

            else:
                result["error"] = "Invalid action"
            
            return jsonify(result)
            
        @self.flask_app.route('/api/window-position', methods=['GET'])
        def window_position():
            """Get the current window position"""
            from flask import jsonify

            pos = get_window_position()
            if pos:
                return jsonify({"success": True, "position": pos})
            return jsonify({"success": False, "error": "Could not get window handle"})
                
        @self.flask_app.route('/api/log', methods=['POST'])
        def client_log():
            """Log messages from the client"""
            from flask import request, jsonify
            
            data = request.json
            message = data.get('message', '')
            level = data.get('level', 'info').lower()
            
            if level == 'debug':
                logger.debug(f"Client: {message}")
            elif level == 'info':
                logger.info(f"Client: {message}")
            elif level == 'warning':
                logger.warning(f"Client: {message}")
            elif level == 'error':
                logger.error(f"Client: {message}")
            else:
                logger.info(f"Client ({level}): {message}")
                
            return jsonify({"success": True})
        
        return self.flask_app
        
    def start_server(self):
        """Start the Flask server in a thread"""
        if not _local_port_available(self.port):
            _fail_port_in_use(self.port)

        if self.flask_app is None:
            self.initialize_flask()
            
        # Run the Flask app in a thread
        threading.Thread(target=lambda: serve(
            self.flask_app,
            host='127.0.0.1',
            port=self.port,
            threads=8,
        ), daemon=True).start()
        
        logger.info(f"Flask server started on http://127.0.0.1:{self.port}")
    
    def validate_token(self, oauth_token=None):
        """Probe token status: 'valid', 'invalid', or 'unreachable'."""
        token = oauth_token or self.oauth_token
        if not token:
            return "invalid"

        from catswitch.auth_twitch import probe_twitch_token

        status, _user = probe_twitch_token(self.client_id, token)
        return status

    def token_monitor(self):
        """Periodically check token validity; ignore offline / unreachable."""
        from catswitch.auth_twitch import TOKEN_INVALID, TOKEN_VALID, TOKEN_UNREACHABLE

        while True:
            time.sleep(self.token_check_interval)

            try:
                from catswitch.web_interface import OAUTH_TOKEN, notify_oauth_token_expired
            except ImportError:
                continue

            token = OAUTH_TOKEN
            if not token:
                self.token_valid = True
                continue

            status = self.validate_token(token)
            if status == TOKEN_UNREACHABLE:
                # Offline screen handles connectivity; do not claim auth expired.
                continue
            if status == TOKEN_INVALID:
                try:
                    from catswitch.web_interface import try_refresh_active_oauth_token
                    if try_refresh_active_oauth_token():
                        self.token_valid = True
                        continue
                except ImportError:
                    pass
                if not self.token_valid:
                    continue
                logger.info("Token expired")
                self.token_valid = False
                notify_oauth_token_expired()
            elif status == TOKEN_VALID:
                self.token_valid = True
        
    def set_js_api(self, app_window):
        """Expose JavaScript API functions"""
        global window
        
        try:
            if app_window is not None:
                window = app_window
                self.window = app_window
                
                def js_minimize_window():
                    return self.minimize_or_hide_window()
                
                def js_close_window():
                    schedule_force_process_exit(2.0)
                    if window:
                        window.destroy()
                    return True
                
                def js_set_always_on_top(enabled):
                    if window:
                        logger.info(f"Setting always on top: {enabled}")
                        # Save the setting
                        save_always_on_top(enabled)
                        
                        # First try the direct Windows API method
                        try:
                            import ctypes
                            from ctypes import wintypes
                            import win32gui
                            import win32con
                            
                            # Log PyWebView window information
                            logger.info(f"Window object properties: {dir(window)}")
                            if hasattr(window, 'gui'):
                                logger.info(f"Window.gui properties: {dir(window.gui)}")
                            
                            user32 = ctypes.windll.user32
                            hwnd = None
                            
                            # Method 1: Direct handle access
                            if hasattr(window, 'gui') and hasattr(window.gui, 'handle'):
                                hwnd = window.gui.handle
                                logger.info(f"Using window.gui.handle: {hwnd}")
                            
                            # Method 2: For WinForms implementation
                            if not hwnd and hasattr(window, 'gui') and hasattr(window.gui, 'main_window'):
                                if hasattr(window.gui.main_window, 'Handle'):
                                    hwnd = window.gui.main_window.Handle.ToInt64()
                                    logger.info(f"Using WinForms handle: {hwnd}")
                            
                            # Method 3: Try to find window by title
                            if not hwnd:
                                hwnd = win32gui.FindWindow(None, 'CatSwitch')
                                logger.info(f"Using FindWindow by title: {hwnd}")
                            
                            # Method 4: Get foreground window (fallback)
                            if not hwnd or hwnd == 0:
                                hwnd = user32.GetForegroundWindow()
                                logger.info(f"Using foreground window handle: {hwnd}")
                                
                            if hwnd and hwnd != 0:
                                # Set window to be topmost or not
                                HWND_TOPMOST = -1
                                HWND_NOTOPMOST = -2
                                SWP_NOMOVE = 0x0002
                                SWP_NOSIZE = 0x0001
                                
                                # Choose the appropriate flag based on the 'enabled' parameter
                                flag = HWND_TOPMOST if enabled else HWND_NOTOPMOST
                                
                                # Alternative method using win32gui
                                try:
                                    if enabled:
                                        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, 
                                                            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
                                    else:
                                        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, 
                                                            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
                                    logger.info(f"Successfully set always on top: {enabled} via win32gui")
                                    return True
                                except Exception as e:
                                    logger.error(f"Error setting always on top via win32gui: {e}")
                                
                                # Fall back to the original method
                                try:
                                    # Set the window position
                                    result = user32.SetWindowPos(
                                        hwnd, 
                                        flag,
                                        0, 0,  # x, y (ignored with SWP_NOMOVE)
                                        0, 0,  # cx, cy (ignored with SWP_NOSIZE)
                                        SWP_NOMOVE | SWP_NOSIZE
                                    )
                                    
                                    if result:
                                        logger.info(f"Successfully set always on top: {enabled} via Win32 API")
                                        return True
                                    else:
                                        error = ctypes.WinError()
                                        logger.error(f"SetWindowPos failed: {error}")
                                except Exception as e:
                                    logger.error(f"Error in SetWindowPos: {e}")
                            else:
                                logger.error("Could not get valid window handle, got: " + str(hwnd))
                        except Exception as e:
                            logger.error(f"Error setting always on top via Win32 API: {e}", exc_info=True)
                        
                        # If Win32 API failed, try the web API method
                        try:
                            response = requests.post('http://127.0.0.1:51111/api/always-on-top', 
                                                     json={'enabled': enabled})
                            if response.status_code == 200:
                                logger.info(f"Successfully set always on top: {enabled} via web API")
                                return True
                        except Exception as e:
                            logger.error(f"Error setting always on top via web API: {e}", exc_info=True)
                            
                    return False
                
                def js_is_always_on_top():
                    """Check if the window is currently set as always-on-top"""
                    if window:
                        logger.info("Checking always-on-top state")
                        try:
                            import ctypes
                            from ctypes import wintypes
                            import win32gui
                            import win32con
                            
                            user32 = ctypes.windll.user32
                            hwnd = None
                            
                            # Method 1: Direct handle access
                            if hasattr(window, 'gui') and hasattr(window.gui, 'handle'):
                                hwnd = window.gui.handle
                                logger.info(f"Using window.gui.handle: {hwnd}")
                            
                            # Method 2: For WinForms implementation
                            if not hwnd and hasattr(window, 'gui') and hasattr(window.gui, 'main_window'):
                                if hasattr(window.gui.main_window, 'Handle'):
                                    hwnd = window.gui.main_window.Handle.ToInt64()
                                    logger.info(f"Using WinForms handle: {hwnd}")
                            
                            # Method 3: Try to find window by title
                            if not hwnd:
                                hwnd = win32gui.FindWindow(None, 'CatSwitch')
                                logger.info(f"Using FindWindow by title: {hwnd}")
                            
                            # Method 4: Get foreground window (fallback)
                            if not hwnd or hwnd == 0:
                                hwnd = user32.GetForegroundWindow()
                                logger.info(f"Using foreground window handle: {hwnd}")
                                
                            if hwnd and hwnd != 0:
                                # Get the current window style
                                style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                                
                                # Check if WS_EX_TOPMOST flag is set
                                is_topmost = bool(style & win32con.WS_EX_TOPMOST)
                                logger.info(f"Window is topmost: {is_topmost}")
                                
                                return is_topmost
                            else:
                                logger.error("Could not get valid window handle to check always-on-top state")
                        except Exception as e:
                            logger.error(f"Error checking always-on-top state: {e}", exc_info=True)
                    
                    # Default to False if we couldn't determine
                    return False
                
                def js_toggle_debug():
                    """Toggle debug console visibility by restarting with debug enabled"""
                    try:
                        logger.info("F12 pressed - restarting with debug console enabled")
                        
                        # Close current window
                        if window:
                            window.destroy()
                        
                        # Restart with debug enabled (frozen: exe only; dev: -m catswitch)
                        import subprocess
                        import sys
                        if getattr(sys, "frozen", False):
                            subprocess.Popen([sys.executable, "--debug"])
                        else:
                            subprocess.Popen([sys.executable, "-m", "catswitch", "--debug"])
                        
                        return True
                    except Exception as e:
                        logger.error(f"Error toggling debug console: {e}")
                        return False

                def js_focus_window():
                    return focus_window()

                def js_resize_window(width, height):
                    if not window:
                        return False
                    try:
                        width = int(width)
                        height = int(height)
                        min_w, min_h = get_home_view_min_size()
                        window.min_size = (min_w, min_h)

                        form = getattr(window, 'gui', None)
                        if form and hasattr(form, 'MinimumSize') and hasattr(form, '_scale'):
                            from System.Drawing import Size
                            scale = form._scale
                            form.MinimumSize = Size(int(min_w * scale), int(min_h * scale))

                        window.resize(width, height)
                        logger.info(f"Resized window to {width}x{height}")
                        return True
                    except Exception as e:
                        logger.error(f"Error resizing window: {e}", exc_info=True)
                        return False

                def js_set_minimize_to_tray(enabled):
                    enabled = bool(enabled)
                    save_window_settings({"minimize_to_tray": enabled})
                    self.sync_tray_icon(enabled)
                    logger.info("Minimize to tray setting updated: %s", enabled)
                    return True

                def js_get_minimize_to_tray():
                    return load_minimize_to_tray()

                def js_set_autostart_with_windows(enabled):
                    ok = save_window_settings(
                        {"autostart_with_windows": bool(enabled)}
                    )
                    logger.info(
                        "Autostart with Windows updated: %s (ok=%s)", enabled, ok
                    )
                    return bool(ok)

                def js_get_autostart_with_windows():
                    return load_autostart_with_windows()

                # Expose functions individually - this is key for your PyWebView version
                window.expose(js_minimize_window)
                window.expose(js_close_window)
                window.expose(js_set_always_on_top)
                window.expose(js_is_always_on_top)
                window.expose(js_set_minimize_to_tray)
                window.expose(js_get_minimize_to_tray)
                window.expose(js_set_autostart_with_windows)
                window.expose(js_get_autostart_with_windows)
                window.expose(js_toggle_debug)
                window.expose(js_focus_window)
                window.expose(js_resize_window)
                
                logger.info("JavaScript API functions exposed successfully")
        except Exception as e:
            logger.error(f"Failed to expose JavaScript API: {str(e)}")
    
    def create_window(self, debug=False):
        """Create the PyWebView window"""
        global window
        
        # Start Flask server in a thread
        self.start_server()
        
        # Load saved window position and always on top setting
        x, y = load_window_position()
        always_on_top = load_always_on_top()
        compact_view = load_home_compact_view()
        width, height = get_home_view_size(compact_view)
        min_width, min_height = get_home_view_min_size()
        
        # Create window
        logger.info(
            f"Creating PyWebView window at position ({x}, {y}), "
            f"size ({width}, {height}), min_size ({min_width}, {min_height}), "
            f"compact={compact_view}, always on top: {always_on_top}"
        )
        
        # Create a frameless window
        window = webview.create_window(
            title='CatSwitch',
            url=f'http://127.0.0.1:{self.port}',
            width=width,
            height=height,
            x=x,
            y=y,
            resizable=False,
            frameless=True,
            easy_drag=False,
            min_size=(min_width, min_height),
            background_color='#282828',
            text_select=True
        )
        
        # Set up JavaScript API
        self.set_js_api(window)
        logger.info("JavaScript API exposed")

        threading.Thread(target=self.token_monitor, daemon=True).start()
        logger.info("Token monitor started")
        
        # Add event handlers directly
        def on_shown():
            logger.info("Window shown")
            try:
                apply_app_window_icon(window)
            except Exception as e:
                logger.error(f"Failed to apply app icon: {e}", exc_info=True)

            try:
                self.sync_tray_icon()
            except Exception as e:
                logger.error(f"Failed to initialize tray icon: {e}", exc_info=True)

            # PyWebView can open at the wrong height until an explicit resize runs.
            try:
                view_w, view_h = get_home_view_size(compact_view)
                min_w, min_h = get_home_view_min_size()
                window.min_size = (min_w, min_h)

                form = getattr(window, 'gui', None)
                if form and hasattr(form, 'MinimumSize') and hasattr(form, '_scale'):
                    from System.Drawing import Size
                    scale = form._scale
                    form.MinimumSize = Size(int(min_w * scale), int(min_h * scale))

                window.resize(view_w, view_h)
                logger.info(f"Applied home view size on shown: {view_w}x{view_h}")
            except Exception as e:
                logger.error(f"Failed to apply home view size on shown: {e}", exc_info=True)

            # Apply always on top setting if enabled (after window is shown)
            if always_on_top:
                # Add a small delay to ensure window is fully ready
                import threading
                def apply_always_on_top():
                    import time
                    time.sleep(0.5)  # Wait 500ms for window to be fully ready
                    try:
                        import win32gui
                        import win32con
                        hwnd = win32gui.FindWindow(None, 'CatSwitch')
                        if hwnd:
                            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, 
                                                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
                            logger.info("Successfully applied always on top setting after window shown")
                        else:
                            logger.error("Could not find window handle for always on top after window shown")
                    except Exception as e:
                        logger.error(f"Error applying always on top setting after window shown: {e}")
                
                # Run in a separate thread to avoid blocking
                threading.Thread(target=apply_always_on_top, daemon=True).start()
            else:
                pass

            if self.start_minimized and not self._applied_start_minimized:
                self._applied_start_minimized = True
                try:
                    self.minimize_window()
                    logger.info("Started minimized (--minimized)")
                except Exception as e:
                    logger.error(
                        "Failed to apply start-minimized: %s", e, exc_info=True
                    )
        
        def on_closing():
            # Inno Restart Manager / WM_CLOSE can destroy the window while the
            # Python process keeps running; always schedule a hard exit first.
            logger.info("Window closing")
            schedule_force_process_exit(2.0)
            try:
                self.sync_tray_icon(False)
            except Exception as e:
                logger.error(f"Failed to stop tray icon: {e}")
            # Save current window position before closing
            try:
                pos = get_window_position()
                if pos:
                    save_window_position(pos["x"], pos["y"])
                    logger.info(f"Saved window position: ({pos['x']}, {pos['y']})")
            except Exception as e:
                logger.error(f"Failed to save window position: {e}")
            
            # Clean up threads and resources (never block long — Twitch I/O is timed)
            try:
                from catswitch.web_interface import apply_default_title_on_shutdown
                apply_default_title_on_shutdown(timeout_sec=1.5)

                # Stop the Flask server
                if hasattr(self, 'flask_app') and self.flask_app:
                    logger.info("Stopping Flask server...")
                    # The Flask server thread will stop when the main thread exits
                    # since it's a daemon thread
                
                # Stop game detection
                from catswitch.detect_game import stop_game_detection
                stop_game_detection()
                
                logger.info("Cleanup completed")
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")
        
        # Connect event handlers
        window.events.shown += on_shown
        window.events.closing += on_closing
        
        # Start the webview
        logger.info("Starting PyWebView")
        webview.start(debug=debug)
        # If the GUI loop returned but something still keeps us alive, hard-exit.
        schedule_force_process_exit(0.5)
        os._exit(0)


def run_desktop_app(client_id, oauth_token, debug=False, start_minimized=False):
    """Run the desktop application"""
    from catswitch.console_log import install_console_capture

    install_console_capture()
    import signal
    import sys

    if not ensure_single_instance():
        sys.exit(0)
    
    def signal_handler(sig, frame):
        logger.info("Received shutdown signal, cleaning up...")
        try:
            from catswitch.detect_game import stop_game_detection
            stop_game_detection()
            from catswitch.web_interface import apply_default_title_on_shutdown
            apply_default_title_on_shutdown()
        except Exception as e:
            logger.error(f"Error during signal cleanup: {e}")
        sys.exit(0)
    
    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("Starting CatSwitch desktop application")
    app = DesktopApp(client_id, oauth_token, start_minimized=start_minimized)
    app.create_window(debug=debug)


if __name__ == "__main__":
    from catswitch.auth_twitch import TWITCH_CLIENT_ID, resolve_startup_token

    oauth_token = resolve_startup_token(TWITCH_CLIENT_ID)
    run_desktop_app(TWITCH_CLIENT_ID, oauth_token) 