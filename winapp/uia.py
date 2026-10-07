"""Thin Windows UI Automation (UIA) layer used to read and drive the QQ desktop window.

QQ NT is an Electron/Chromium app. Chromium publishes its DOM through UIA like this:

    HTML ``aria-label`` / text  -> ``Name``
    HTML ``class``              -> ``ClassName``
    HTML ``id``                 -> ``AutomationId``

which is the same information the macOS build read through ``AXDescription`` / ``AXDOMClassList`` /
``AXDOMIdentifier``. ``dump_tree`` therefore produces the same JSON shape the macOS app produced, so
``snapshot.parse_snapshot`` works unchanged.

Every function here must run on a thread that has initialised COM; ``winapp.worker`` owns that thread.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

import comtypes
import comtypes.client

try:                                    # normal case, and the only one that works in a frozen app: wrapper already generated
    from comtypes.gen import UIAutomationClient as UIA
except ImportError:                     # first run from source: generate the wrapper from the type library
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as UIA  # noqa: E402

# UIA property ids (UIAutomationClient.h)
P_BOUNDS = 30001
P_CONTROL_TYPE = 30003
P_NAME = 30005
P_HAS_FOCUS = 30008
P_FOCUSABLE = 30009
P_ENABLED = 30010
P_AUTOMATION_ID = 30011
P_CLASS_NAME = 30012
P_NATIVE_HWND = 30020
P_OFFSCREEN = 30022
P_IS_INVOKE = 30031
P_IS_TEXT = 30040
P_IS_VALUE = 30043
P_VALUE = 30045
P_ARIA_ROLE = 30101
P_LOCALIZED_TYPE = 30004

# UIA control type id -> the macOS accessibility role name the Python parser expects
ROLE_BY_TYPE = {
    50000: "AXButton", 50002: "AXCheckBox", 50003: "AXComboBox", 50004: "AXTextField", 50005: "AXLink",
    50006: "AXImage", 50007: "AXRow", 50008: "AXList", 50009: "AXMenu", 50010: "AXMenuBar",
    50011: "AXMenuItem", 50020: "AXStaticText", 50021: "AXToolbar", 50026: "AXGroup", 50030: "AXWebArea",
    50032: "AXWindow", 50033: "AXGroup",
}
T_TEXT, T_EDIT, T_DOCUMENT, T_IMAGE = 50020, 50004, 50030, 50006

_uia = None
_cache_requests: dict[tuple, object] = {}


def automation():
    global _uia
    if _uia is None:
        _uia = comtypes.CoCreateInstance(UIA.CUIAutomation._reg_clsid_, interface=UIA.IUIAutomation,
                                         clsctx=comtypes.CLSCTX_INPROC_SERVER)
    return _uia


def cache_request(props: tuple, scope):
    key = (props, scope)
    request = _cache_requests.get(key)
    if request is None:
        request = automation().CreateCacheRequest()
        for prop in props:
            request.AddProperty(prop)
        request.TreeScope = scope
        request.TreeFilter = automation().RawViewCondition
        _cache_requests[key] = request
    return request


# --- generic element helpers ---------------------------------------------------------------------------

def children(element):
    """Cached children when the element was built with a cache request, otherwise a live lookup."""
    try:
        array = element.GetCachedChildren()          # a NULL pointer (falsy) means "cached, no children"
    except comtypes.COMError:
        try:
            array = element.FindAll(UIA.TreeScope_Children, automation().RawViewCondition)
        except comtypes.COMError:
            return []
    if not array:
        return []
    return [array.GetElement(i) for i in range(array.Length)]


def prop(element, prop_id, cached=True):
    try:
        return element.GetCachedPropertyValue(prop_id) if cached else element.GetCurrentPropertyValue(prop_id)
    except Exception:
        return None


def rect_of(element, cached=True):
    try:
        r = element.CachedBoundingRectangle if cached else element.CurrentBoundingRectangle
        return (r.left, r.top, r.right, r.bottom)
    except Exception:
        return None


def name_of(element, cached=True):
    try:
        return (element.CachedName if cached else element.CurrentName) or ""
    except Exception:
        return ""


def class_of(element, cached=True):
    try:
        return (element.CachedClassName if cached else element.CurrentClassName) or ""
    except Exception:
        return ""


def id_of(element, cached=True):
    try:
        return (element.CachedAutomationId if cached else element.CurrentAutomationId) or ""
    except Exception:
        return ""


def type_of(element, cached=True):
    try:
        return element.CachedControlType if cached else element.CurrentControlType
    except Exception:
        return 0


def element_from_handle(hwnd: int, props: tuple, scope=None):
    scope = UIA.TreeScope_Subtree if scope is None else scope
    return automation().ElementFromHandleBuildCache(hwnd, cache_request(props, scope))


def find_all(root, **conditions):
    """Live search below ``root`` for elements whose Name/ClassName/AutomationId/ControlType match."""
    try:
        array = root.FindAll(UIA.TreeScope_Descendants, _condition(conditions))
    except comtypes.COMError:
        return []
    return [array.GetElement(i) for i in range(array.Length)] if array else []


def find_first(root, **conditions):
    """First matching descendant or None."""
    try:
        found = root.FindFirst(UIA.TreeScope_Descendants, _condition(conditions))
    except comtypes.COMError:
        return None
    return found if found else None


def _condition(conditions):
    ids = {"name": P_NAME, "cls": P_CLASS_NAME, "aid": P_AUTOMATION_ID, "ctype": P_CONTROL_TYPE}
    parts = [automation().CreatePropertyCondition(ids[k], v) for k, v in conditions.items()]
    if not parts:
        return automation().CreateTrueCondition()
    cond = parts[0]
    for extra in parts[1:]:
        cond = automation().CreateAndCondition(cond, extra)
    return cond


def get_pattern(element, pattern_id, interface):
    """The UIA control pattern of ``element`` as ``interface``, or None when it does not support it."""
    try:
        unknown = element.GetCurrentPattern(pattern_id)
        return unknown.QueryInterface(interface) if unknown else None
    except (comtypes.COMError, ValueError, AttributeError):
        return None


def invoke(element) -> bool:
    """Press a button-like element through the UIA Invoke pattern (no mouse involved)."""
    pattern = get_pattern(element, UIA.UIA_InvokePatternId, UIA.IUIAutomationInvokePattern)
    if pattern is None:
        return False
    try:
        pattern.Invoke()
        return True
    except comtypes.COMError:
        return False


def set_focus(element) -> bool:
    try:
        element.SetFocus()
        return True
    except comtypes.COMError:
        return False


def scroll_into_view(element) -> bool:
    pattern = get_pattern(element, UIA.UIA_ScrollItemPatternId, UIA.IUIAutomationScrollItemPattern)
    if pattern is None:
        return False
    try:
        pattern.ScrollIntoView()
        return True
    except comtypes.COMError:
        return False


def is_offscreen(element) -> bool:
    try:
        return bool(element.CurrentIsOffscreen)
    except comtypes.COMError:
        return True


def live_children(element) -> list:
    try:
        array = element.FindAll(UIA.TreeScope_Children, automation().RawViewCondition)
    except comtypes.COMError:
        return []
    return [array.GetElement(i) for i in range(array.Length)] if array else []


def has_focus(element) -> bool:
    try:
        return bool(element.CurrentHasKeyboardFocus)
    except comtypes.COMError:
        return False


def focused_element():
    try:
        return automation().GetFocusedElement()
    except comtypes.COMError:
        return None


def same(a, b) -> bool:
    try:
        return bool(automation().CompareElements(a, b))
    except comtypes.COMError:
        return False


# --- tree dump (same JSON shape as the macOS accessibility dump) -----------------------------------------

DUMP_PROPS = (P_NAME, P_CONTROL_TYPE, P_AUTOMATION_ID, P_CLASS_NAME, P_BOUNDS, P_IS_VALUE, P_OFFSCREEN)
MAX_DEPTH = 42


def dump_tree(root_element) -> dict:
    """Walk a cached subtree into nested dicts: role/desc/value/domId/classes/children.

    * ``Text`` controls carry their text in ``value`` (like AXStaticText), everything else puts ``Name`` in
      ``desc`` (like AXDescription).
    * Edit/Document controls expose their current text as ``value`` (the editor draft).
    """
    return _dump(root_element, 0)


EDITOR_CLASS = "ExEditor-qq-msg-editor"      # the ProseMirror message box at the bottom of a chat


def pattern_text(element) -> str:
    """Full text of an element through the UIA Text pattern ('' when unavailable)."""
    pattern = get_pattern(element, UIA.UIA_TextPatternId, UIA.IUIAutomationTextPattern)
    if pattern is None:
        return ""
    try:
        return pattern.DocumentRange.GetText(-1) or ""
    except (comtypes.COMError, ValueError, AttributeError):
        return ""


def _dump(element, depth):
    ctype = type_of(element)
    name = name_of(element)
    node = {"role": ROLE_BY_TYPE.get(ctype, "AXGroup")}
    if ctype == T_TEXT:
        if name:
            node["value"] = name
    elif name:
        node["desc"] = name
    aid = id_of(element)
    if aid:
        node["domId"] = aid
    classes = class_of(element).split()
    if classes:
        node["classes"] = classes
    if EDITOR_CLASS in classes:
        node["role"] = "AXTextArea"
        node["value"] = "" if "is-empty" in classes else pattern_text(element)
    rect = rect_of(element)
    if rect and rect[2] > rect[0] and rect[3] > rect[1]:
        node["rect"] = rect
    if depth < MAX_DEPTH:
        kids = [_dump(child, depth + 1) for child in children(element)]
        if kids:
            node["children"] = kids
    return node


# --- Win32 window lookup ----------------------------------------------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def process_image(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def window_title(hwnd) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def window_class(hwnd) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def top_level_windows(image_name: str = "QQ.exe") -> list[dict]:
    """Visible top-level windows owned by a process whose executable is ``image_name``."""
    found = []

    def callback(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        image = process_image(pid.value)
        if image.lower().endswith("\\" + image_name.lower()):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            found.append({"hwnd": hwnd, "pid": pid.value, "title": window_title(hwnd), "cls": window_class(hwnd),
                          "visible": bool(user32.IsWindowVisible(hwnd)), "minimized": bool(user32.IsIconic(hwnd)),
                          "rect": (rect.left, rect.top, rect.right, rect.bottom), "image": image})
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found
