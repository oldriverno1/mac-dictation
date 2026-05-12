-- Dictation: hold Right Command anywhere, speak, release, transcript pastes at cursor.

local M = {}

local DAEMON = "http://127.0.0.1:47823"
local HEADERS = {["Content-Type"] = "application/json"}

-- IOKit device-specific flag mask for the right Command key.
-- NX_DEVICERCMDKEYMASK = 0x10 (bit 4 of the low byte of CGEventFlags).
-- We must use this rather than ev:getFlags().cmd, which is set when *either* Cmd is down.
local RIGHT_CMD_MASK = 0x10
local RIGHT_CMD_KEYCODE = 54  -- Apple keyCode for Right Command

-- ---------- State ----------
M.menubar = nil
M.recording = false
M.saved_clipboard = nil
M.saved_changeCount = nil

-- ---------- Menubar ----------
local ICONS = {
    idle         = "⚪",
    recording    = "🔴",
    transcribing = "🟡",
    pasting      = "🟢",
    error        = "❌",
}

local function set_state(state)
    if M.menubar then M.menubar:setTitle(ICONS[state] or "?") end
end

-- ---------- Sounds ----------
local function play(name)
    local s = hs.sound.getByName(name)
    if s then s:play() end
end

-- ---------- IME detection ----------
local function current_ime()
    -- macism prints the current input source ID, e.g. com.apple.keylayout.ABC
    local out, ok = hs.execute("/Users/Lars/.local/bin/macism", false)
    if not ok or not out then return "" end
    return (out:gsub("%s+$", ""))
end

local IME_EXACT = {
    ["com.apple.keylayout.ABC"]        = "en",
    ["com.apple.keylayout.US"]         = "en",
    ["com.apple.keylayout.British"]    = "en",
    ["com.apple.keylayout.Australian"] = "en",
    ["com.apple.keylayout.Canadian"]   = "en",
    ["com.apple.keylayout.Dvorak"]     = "en",
}

local IME_PREFIX = {
    {"com.apple.inputmethod.TCIM.", "zh"},
    {"com.apple.inputmethod.SCIM.", "zh"},
    {"com.apple.inputmethod.TYIM.", "zh"},
}

local CTX = {
    en = "The following is English dictation. May include technical terms such as MLX, Python, transformer.",
    zh = "以下是繁體中文（台灣）的口述輸入，可能包含技術術語如 MLX、Python、LLM。",
    auto = "",
}

local function resolve_lang(ime)
    if IME_EXACT[ime] then return IME_EXACT[ime], CTX[IME_EXACT[ime]] end
    for _, pair in ipairs(IME_PREFIX) do
        if ime:sub(1, #pair[1]) == pair[1] then
            return pair[2], CTX[pair[2]]
        end
    end
    return "auto", ""
end

-- ---------- IPC (HTTP to daemon) ----------
local function post(path, body, on_done)
    local req_body = hs.json.encode(body)
    hs.http.asyncPost(DAEMON .. path, req_body, HEADERS, function(status, resp_body, _resp_headers)
        if status < 0 then
            on_done({ok = false, error = "daemon_unreachable: " .. tostring(status)})
            return
        end
        local ok_decode, resp = pcall(hs.json.decode, resp_body or "{}")
        if not ok_decode or type(resp) ~= "table" then
            on_done({ok = false, error = "bad_response: " .. tostring(resp_body)})
            return
        end
        on_done(resp)
    end)
end

-- ---------- Paste flow ----------
local function paste_with_restore(text)
    set_state("pasting")
    -- Save the full clipboard (all types: string, RTF, image, file references) via readAllData.
    M.saved_clipboard = hs.pasteboard.readAllData(nil)
    M.saved_changeCount = hs.pasteboard.changeCount()

    -- Send Escape to collapse any active IME composition buffer.
    hs.eventtap.keyStroke({}, "escape", 0)

    -- Write our text and immediately paste.
    hs.pasteboard.setContents(text)
    hs.eventtap.keyStroke({"cmd"}, "v", 0)

    -- Poll changeCount until it advances past our write, then restore (timeout 1s).
    local started_at = hs.timer.absoluteTime()
    local function poll()
        local elapsed_s = (hs.timer.absoluteTime() - started_at) / 1e9
        if hs.pasteboard.changeCount() > (M.saved_changeCount + 1) or elapsed_s > 1.0 then
            if M.saved_clipboard then
                hs.pasteboard.writeAllData(nil, M.saved_clipboard)
            end
            set_state("idle")
            return
        end
        hs.timer.doAfter(0.05, poll)
    end
    hs.timer.doAfter(0.05, poll)
end

-- ---------- Right Cmd listener ----------
local function on_right_cmd_down()
    if M.recording then return end
    M.recording = true
    set_state("recording")
    play("Tink")
    local ime = current_ime()
    local lang, ctx = resolve_lang(ime)
    post("/start", {language = lang, context = ctx}, function(resp)
        if not resp.ok then
            M.recording = false
            set_state("error")
            play("Funk")
            hs.notify.new({title = "Dictation", informativeText = tostring(resp.error)}):send()
            hs.timer.doAfter(3, function() set_state("idle") end)
        end
    end)
end

local function on_right_cmd_up()
    if not M.recording then return end
    M.recording = false
    set_state("transcribing")
    post("/stop", {}, function(resp)
        if resp.ok and resp.text and #resp.text > 0 then
            paste_with_restore(resp.text)
        elseif resp.ok then
            set_state("idle")  -- empty transcription
        else
            set_state("error")
            play("Funk")
            hs.notify.new({title = "Dictation", informativeText = tostring(resp.error)}):send()
            hs.timer.doAfter(3, function() set_state("idle") end)
        end
    end)
end

-- ---------- Bootstrap ----------
function M.start()
    M.menubar = hs.menubar.new()
    set_state("idle")

    -- flagsChanged fires for every modifier change. Filter to events whose keyCode is
    -- the Right Command (54). The post-transition raw flag tells us whether right cmd
    -- is now down (bit set) or now up (bit cleared). This works correctly even when
    -- the left Command is simultaneously held.
    M.tap = hs.eventtap.new({hs.eventtap.event.types.flagsChanged}, function(ev)
        if ev:getKeyCode() ~= RIGHT_CMD_KEYCODE then return false end
        local raw = ev:rawFlags()
        local right_cmd_down = (raw & RIGHT_CMD_MASK) ~= 0
        if right_cmd_down then
            on_right_cmd_down()
        else
            on_right_cmd_up()
        end
        return false
    end)
    M.tap:start()
    print("[dictation] started, right-cmd listener active")
end

M.start()
return M
