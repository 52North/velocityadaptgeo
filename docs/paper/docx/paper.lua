-- pandoc Lua filter for `make docx` (run from docs/paper). Fills in what pandoc cannot take from
-- the LaTeX source and puts it into the paragraph styles of template/Mustertext_Tagungsband.docx
-- (custom-style = Word style name): title block, citations + bibliography from the BibTeX
-- output (build/main.bbl, formatted by paper.bst), table rows from the CSV, source lines.

local BBL = 'build/main.bbl'
local TAB = pandoc.RawInline('openxml', '<w:r><w:tab/></w:r>')

local function read_file(path)
  local f = assert(io.open(path, 'r'))
  local text = f:read('a')
  f:close()
  return text
end

-- Macro definitions (\bibinname, \bibnodatename, ...) for LaTeX snippets parsed below
local SHIM = read_file('docx/shim.tex')

local function latex_blocks(tex)
  return pandoc.read(SHIM .. tex, 'latex').blocks
end

local function latex_inlines(tex)
  return pandoc.utils.blocks_to_inlines(latex_blocks(tex))
end

local function styled(style, inlines)
  return pandoc.Div(pandoc.Para(inlines), {['custom-style'] = style})
end

-- --- Bibliography: \bibitem[{Author(year)}]{key} text ------------------------------------
-- Returns the citation labels by key and the formatted entries in bbl order.
local function read_bibliography()
  local refs, entries = {}, pandoc.Blocks{}
  local bbl = read_file(BBL):gsub('\\end{thebibliography}.*$', '')
  local pos = bbl:find('\\bibitem', 1, true)
  while pos do
    local next_pos = bbl:find('\\bibitem', pos + 1, true)
    local item = bbl:sub(pos + #'\\bibitem', next_pos and next_pos - 1 or -1)
    local label, key, body = item:match('^(%b[])(%b{})(.*)$')
    local author, year = label:sub(3, -3):match('^(.*)%((.-)%)$')
    refs[key:sub(2, -2)] = {author = latex_inlines(author), year = latex_inlines(year)}
    entries:insert(styled('Literaturliste', latex_inlines(body)))
    pos = next_pos
  end
  return refs, entries
end

local REFS, ENTRIES = read_bibliography()

-- \citep -> "(Vila et al. 2014)", \citet -> "Vila et al. (2014)"; several keys joined by ", "
function Cite(cite)
  local parts = {}
  for _, c in ipairs(cite.citations) do
    local ref = assert(REFS[c.id], 'citation key not in ' .. BBL .. ': ' .. c.id)
    local part = pandoc.Inlines{}
    part:extend(ref.author)
    part:insert(pandoc.Space())
    if c.mode == 'AuthorInText' then
      part:insert(pandoc.Str('('))
      part:extend(ref.year)
      part:insert(pandoc.Str(')'))
    else
      part:extend(ref.year)
    end
    table.insert(parts, part)
  end
  local out = pandoc.Inlines{}
  for i, part in ipairs(parts) do
    if i > 1 then out:extend{pandoc.Str(','), pandoc.Space()} end
    out:extend(part)
  end
  if cite.citations[1].mode == 'NormalCitation' then
    out:insert(1, pandoc.Str('('))
    out:insert(pandoc.Str(')'))
  end
  return out
end

-- --- Source lines: "Source:" + tab + text, as in the template ---------------------------------
local function source_line(div, style)
  local inlines = pandoc.utils.blocks_to_inlines(div.content)
  for i, el in ipairs(inlines) do
    if el.t == 'Str' and el.text:sub(-1) == ':' then
      if inlines[i + 1] and inlines[i + 1].t == 'Space' then inlines[i + 1] = TAB end
      break
    end
  end
  return styled(style, inlines)
end

function Div(div)
  if div.classes:includes('tabsourceline') then return source_line(div, 'Tabellenquelle') end
  if div.classes:includes('figsourceline') then return source_line(div, 'Abbildungsquelle') end
end

-- The docx writer ignores a height-only size (figure with two images side by side) and
-- stretches the image to the text width: derive the width from the image's aspect ratio.
-- Path as in the Makefile: \graphicspath{figures/}.
-- Alt text (Word: descr): the LaTeX source line breaks and indentation collapsed to spaces.
function Image(img)
  img.caption = {pandoc.Str((pandoc.utils.stringify(img.caption):gsub('%s+', ' ')))}
  local height = img.attributes.height
  if height and not img.attributes.width then
    local value, unit = height:match('^([%d.]+)(%a+)$')
    local size = pandoc.image.size(read_file('figures/' .. img.src))
    img.attributes.width = string.format('%.2f%s', value * size.width / size.height, unit)
  end
  return img
end

-- Cross references (Figure 1, Table 1) as plain text, like \hypersetup{hidelinks} in the PDF;
-- links to URLs stay
function Link(link)
  if link.target:sub(1, 1) == '#' then return link.content end
end

-- pandoc lays out a figure with several blocks as a table, side by side; keep only the images
-- in the figure and put the source lines below it
function Figure(fig)
  local sources = pandoc.Blocks{}
  fig.content = fig.content:filter(function(block)
    local is_source = block.t == 'Div' and block.attributes['custom-style'] == 'Abbildungsquelle'
    if is_source then sources:insert(block) end
    return not is_source
  end)
  return pandoc.Blocks{fig} .. sources
end

-- --- Table rows from the CSV ----------------------------------------------------------------
-- Table tab:<name> comes from tables/tab-<name>.tex; its \csvreader{file}{col=\macro,...}{row}
-- is expanded here (shim.tex drops it for pandoc). Assumes a plain CSV without quoted fields.
local function csv_rows(tex)
  local _, _, _, file, keys, template =
    tex:find('\\csvreader%s*(%b[])%s*(%b{})%s*(%b{})%s*(%b{})')
  if not file then return nil end
  local macro_of = {}
  for col, macro in keys:gmatch('([%w_]+)%s*=%s*\\(%a+)') do macro_of[col] = macro end
  template = ('\n' .. template:sub(2, -2)):gsub('([^\\])%%[^\n]*', '%1')

  local lines = {}
  for line in read_file(file:sub(2, -2)):gmatch('[^\r\n]+') do table.insert(lines, line) end
  local header = {}
  for col in lines[1]:gmatch('[^,]+') do table.insert(header, col) end

  local rows_tex = {}
  for i = 2, #lines do
    local values, j = {}, 1
    for value in (lines[i] .. ','):gmatch('([^,]*),') do
      values[macro_of[header[j]] or ''] = value
      j = j + 1
    end
    table.insert(rows_tex, (template:gsub('\\(%a+)', values)))
  end
  local tabular = '\\begin{tabular}{' .. string.rep('l', #header) .. '}'
    .. table.concat(rows_tex, '\\\\\n') .. '\\end{tabular}'
  return latex_blocks(tabular)[1].bodies[1].body
end

-- Column alignments from a tabularx spec like |l|*{8}{>{\centering\arraybackslash}X|}
-- (pandoc reads every column as left-aligned)
local ALIGN = {l = 'AlignLeft', c = 'AlignCenter', r = 'AlignRight'}
local function column_aligns(tex)
  local spec = tex:match('\\begin{tabularx}%s*%b{}%s*(%b{})')
  if not spec then return nil end
  spec = spec:sub(2, -2):gsub('[|%s]', '')
  spec = spec:gsub('%*(%b{})(%b{})', function(n, s) return s:sub(2, -2):rep(tonumber(n:sub(2, -2))) end)
  local aligns, i = {}, 1
  while i <= #spec do
    local prefix = spec:match('^>%b{}', i) or ''
    i = i + #prefix
    local col = spec:sub(i, i)
    i = i + 1 + #(spec:match('^%b{}', i + 1) or '')  -- skip p{width} etc.
    if prefix:find('\\centering', 1, true) then col = 'c'
    elseif prefix:find('\\raggedleft', 1, true) then col = 'r' end
    table.insert(aligns, ALIGN[col] or 'AlignLeft')
  end
  return aligns
end

function Table(tbl)
  local name = tbl.identifier:match('^tab:(.+)$')
  if not name then return nil end
  local tex = read_file('tables/tab-' .. name .. '.tex')
  local rows = csv_rows(tex)
  if rows then tbl.bodies[1].body:extend(rows) end
  -- full text width, equal columns (pandoc cannot read the tabularx widths)
  local aligns = column_aligns(tex) or {}
  for i, spec in ipairs(tbl.colspecs) do
    tbl.colspecs[i] = {aligns[i] or spec[1], 1 / #tbl.colspecs}
  end
  return tbl
end

-- --- Title block and bibliography -----------------------------------------------------------
-- The docx writer would put title/author/abstract into its own styles and drops \address, so
-- the block is built here from the metadata pandoc read from main.tex.
function Pandoc(doc)
  local meta = doc.meta
  local front = pandoc.Blocks{styled('Beitragstitel', meta.title)}
  for _, author in ipairs(meta.author) do front:insert(styled('Autorenname', author)) end
  for i, address in ipairs(meta.address or {}) do
    local last = i == #meta.address
    front:insert(styled(last and 'Autorenadresse_1' or 'Autorenadresse_2', address))
  end
  if meta.abstract then
    front:insert(styled('ÜSZusammenfassung', {pandoc.Str('Abstract')}))
    front:extend(meta.abstract)
  end
  meta.title, meta.author, meta.address, meta.abstract, meta.bibliography = nil, nil, nil, nil, nil

  local back = pandoc.Blocks{pandoc.Header(1, 'References', {'references', {'unnumbered'}})}
  back:extend(ENTRIES)
  return pandoc.Pandoc(front .. doc.blocks .. back, meta)
end
