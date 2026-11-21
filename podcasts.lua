-- {"name":"Podcasts","file":"","version":0,"order":7,"arguments":[]}
local service = "http://127.0.0.1:18774"
local title = "Podcasts"
local args = mympd_arguments

local function encode(value)
    return value:gsub("([^%w_.~-])", function(char)
        return string.format("%%%02X", string.byte(char))
    end)
end

local function valid_podcast(id)
    return type(id) == "string" and id:match("^p%x%x%x%x%x%x%x%x%x%x%x%x$") ~= nil
end

local function valid_episode(id)
    return type(id) == "string"
        and id:match("^p%x%x%x%x%x%x%x%x%x%x%x%x%.e%x%x%x%x%x%x%x%x%x%x%x%x$") ~= nil
end

local function request(method, path)
    local headers = method == "POST" and "Content-Type: application/json\r\n" or ""
    local payload = method == "POST" and "{}" or ""
    local rc, status, _, body = mympd.http_client(
        method, service .. path, headers, payload, false
    )
    if rc ~= 0 or status ~= 200 then
        return nil
    end
    return json.decode(body)
end

local function select_field(name, ids, labels, default)
    return {
        name = name,
        type = "select",
        value = ids,
        displayValue = labels,
        defaultValue = default or ids[1] or ""
    }
end

local function podcast_field(name, items)
    local ids, labels = {}, {}
    for _, item in ipairs(items) do
        ids[#ids + 1] = item.id
        local label = item.name
        if item.author and item.author ~= "" then
            label = label .. " (" .. item.author .. ")"
        end
        labels[#labels + 1] = label
    end
    return select_field(name, ids, labels)
end

-- Queue one resolved episode; play_now starts it, otherwise it only joins the queue.
local function queue_episode(path, podcast, play_now)
    local episode = request("GET", path)
    if not episode then
        return "Could not resolve the podcast episode"
    end
    local uri = episode.url:gsub("#.*$", "") .. "#mympd-podcasts=" .. podcast
        .. "&name=" .. encode(episode.name or "")
        .. "&title=" .. encode(episode.title or "")
        .. "&art=" .. encode(episode.artFile or "")
    local rc, result = mympd.api("MYMPD_API_QUEUE_APPEND_URIS", {
        uris = {uri},
        play = play_now
    })
    if rc ~= 0 then
        return result.message or "Could not queue the podcast episode"
    end
    return play_now and "Started podcast episode" or "Added podcast episode to the queue"
end

local function favorite_change(operation, id)
    if not valid_podcast(id) then
        return "Select a podcast"
    end
    if not request("POST", "/favorites/" .. operation .. "/" .. id) then
        return "Could not change the podcast favorites. Reopen the picker to check."
    end
    return operation == "add" and "Podcast saved to favorites" or "Podcast removed from favorites"
end

local action = args.action
local podcast = args.podcast

-- Step: save or remove a chosen podcast.
if args.add_podcast then
    return favorite_change("add", args.add_podcast)
end
if args.remove_podcast then
    return favorite_change("remove", args.remove_podcast)
end

-- Step: play or queue the chosen episode ("<podcast id>.<episode id>").
if args.episode then
    if not valid_episode(args.episode) then
        return "Invalid podcast episode"
    end
    local podcast_id, episode_id = args.episode:match("^(p%x+)%.(e%x+)$")
    return queue_episode("/play/" .. podcast_id .. "/" .. episode_id,
        podcast_id, args.mode ~= "queue")
end

-- Step: search results, then offer to save one.
if args.query then
    local query = args.query
    if type(query) ~= "string" or #query == 0 or #query > 100 then
        return "Enter a podcast name"
    end
    local source = type(args.source) == "string" and args.source or "itunes"
    local results = request("GET", "/search?q=" .. encode(query) .. "&source=" .. encode(source))
    if not results or #results == 0 then
        return "No podcasts found"
    end
    return mympd.dialog("Save a podcast", {
        podcast_field("add_podcast", results)
    }, title)
end

if action == "search" then
    local sources = request("GET", "/sources") or {}
    local fields = {{name = "query", type = "text", value = ""}}
    if #sources > 1 then
        local ids, labels = {}, {}
        for _, item in ipairs(sources) do
            ids[#ids + 1] = item.id
            labels[#labels + 1] = item.name
        end
        fields[#fields + 1] = select_field("source", ids, labels)
    end
    return mympd.dialog("Find a podcast", fields, title)
end

-- Actions below need a selected favorite.
if action == "remove" then
    if not valid_podcast(podcast) then
        return "Select a podcast"
    end
    local label = podcast
    for _, item in ipairs(request("GET", "/favorites") or {}) do
        if item.id == podcast then
            label = item.name
        end
    end
    return mympd.dialog("Remove the selected podcast?", {
        select_field("remove_podcast", {podcast}, {label})
    }, title)
end

if action == "latest" then
    if not valid_podcast(podcast) then
        return "Select a podcast"
    end
    return queue_episode("/latest/" .. podcast, podcast, true)
end

if action == "episodes" then
    if not valid_podcast(podcast) then
        return "Select a podcast"
    end
    local episodes = request("GET", "/episodes/" .. podcast)
    if not episodes or #episodes == 0 then
        return "No episodes found for this podcast"
    end
    local ids, labels = {}, {}
    for _, item in ipairs(episodes) do
        ids[#ids + 1] = podcast .. "." .. item.id
        local label = item.title
        if item.published ~= "" then
            label = item.published .. "  " .. label
        end
        labels[#labels + 1] = label
    end
    return mympd.dialog("Choose an episode", {
        select_field("episode", ids, labels),
        select_field("mode", {"play", "queue"},
            {"Play now", "Add to queue"}, "play")
    }, title)
end

-- Default: show favorites and what to do with them.
local favorites = request("GET", "/favorites")
if type(favorites) ~= "table" then
    return "Could not load podcast favorites"
end
local fields = {}
if #favorites > 0 then
    fields[#fields + 1] = podcast_field("podcast", favorites)
end
fields[#fields + 1] = select_field("action",
    {"episodes", "latest", "search", "remove"},
    {"Choose an episode", "Play latest episode", "Find and save a podcast",
        "Remove selected podcast"},
    #favorites > 0 and "episodes" or "search")
return mympd.dialog(title, fields, title)
