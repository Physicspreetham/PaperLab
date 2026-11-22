-- Shapes the Paper Builder HTML into a printed-paper look in Word.
-- Pass 1: math spans -> real math (native Word equations).
-- Pass 2: options "A) ..." and figures get dedicated paragraph styles.
-- Pass 2b: short options share one line in 4 columns (like the source paper);
--          long options go one per line.
-- Pass 3: lists become literal "N.<tab>" paragraphs with hanging indents
--         (no Word auto-numbering, so numbers always match the preview).
-- Styles (QItem, QOpt, QFig, ...) live in backend/docx_reference.py.

local function tab()
  return pandoc.RawInline('openxml', '<w:r><w:tab/></w:r>')
end

local function styled(style, blocks)
  return pandoc.Div(blocks, pandoc.Attr('', {}, { ['custom-style'] = style }))
end

-- ---- pass 1 ---------------------------------------------------------
-- Words of 4+ letters inside math ("Joule", "Tesla/sec") are units typed in
-- math mode; set them upright like the source paper instead of as
-- letter-spaced italic variables. Arguments of text-like commands and TeX
-- command names themselves (\frac, \sin, \begin{array} ...) are left alone.
local KEEP_CMDS = {
  text = true, mathrm = true, textbf = true, mathbf = true, operatorname = true,
  begin = true, ['end'] = true, color = true, hspace = true, vspace = true,
  textit = true, mbox = true, mathit = true,
}

local function upright_words(tex)
  local keep = {}
  tex = tex:gsub('\\(%a+)(%b{})', function(cmd, body)
    if KEEP_CMDS[cmd] then
      keep[#keep + 1] = '\\' .. cmd .. body
      return '\1' .. #keep .. '\2'
    end
  end)
  tex = tex:gsub('()(%a%a%a%a+)', function(pos, word)
    if pos > 1 and tex:sub(pos - 1, pos - 1) == '\\' then return nil end
    return '\\mathrm{' .. word .. '}'
  end)
  tex = tex:gsub('\1(%d+)\2', function(i) return keep[tonumber(i)] end)
  return tex
end

local function Span(el)
  if el.classes:includes('math') then
    local kind = el.classes:includes('display') and 'DisplayMath' or 'InlineMath'
    local tex = pandoc.utils.stringify(el)
    -- A script with no base ("^{\circ}C") renders as an empty placeholder
    -- box in Word; a leading ^{\circ} is just a degree sign.
    tex = tex:gsub('^%s*%^%s*{%s*\\circ%s*}', '°'):gsub('^%s*%^%s*\\circ', '°')
    return pandoc.Math(kind, upright_words(tex))
  end
end

-- ---- pass 2 ---------------------------------------------------------
local function only_images(inlines)
  local n = 0
  for _, i in ipairs(inlines) do
    if i.t == 'Image' then
      n = n + 1
    elseif i.t ~= 'Space' and i.t ~= 'SoftBreak' and i.t ~= 'LineBreak' then
      return false
    end
  end
  return n > 0
end

-- A paragraph holding only an image is an "implicit figure" and pandoc wraps
-- it in a fixed-width one-cell table. A trailing empty raw run keeps it a plain
-- centred paragraph so wide figures are never clipped.
local function fig_para(inlines)
  local out = pandoc.List(inlines)
  out:insert(pandoc.RawInline('openxml', ''))
  return pandoc.Para(out)
end

local function para_like(el)
  if el.t ~= 'Para' and el.t ~= 'Plain' then return nil end
  local inl = el.content
  if #inl == 0 then return nil end

  -- Option line: "A) text" / "(A) text". Kept as a marker Div here; the
  -- Blocks pass below decides row vs. single-line layout.
  local first = inl[1]
  if first.t == 'Str' then
    local label, rest = first.text:match('^(%(?[A-D]%))(.*)$')
    if label then
      local out = pandoc.List()
      if rest ~= '' then out:insert(pandoc.Str(rest)) end
      for k = 2, #inl do
        if not (k == 2 and rest == '' and inl[k].t == 'Space') then out:insert(inl[k]) end
      end
      return pandoc.Div({ pandoc.Para(out) }, pandoc.Attr('', { 'qopt' }, { label = label }))
    end
  end

  if only_images(inl) then
    return styled('QFig', { fig_para(inl) })
  end
  return nil
end

local function Para(el) return para_like(el) end
local function Plain(el)
  -- Table cells / list items use Plain; only restyle figures there.
  if only_images(el.content) then return styled('QFig', { fig_para(el.content) }) end
end

local function Figure(el)
  local inl = pandoc.List()
  for _, b in ipairs(el.content) do
    if b.t == 'Para' or b.t == 'Plain' then inl:extend(b.content) end
  end
  -- Inner paragraphs were already restyled (QFig Divs) by the Para handler:
  -- unwrap the Figure so pandoc does not box it in a fixed-width table.
  if #inl == 0 then return el.content end
  return styled('QFig', { fig_para(inl) })
end

-- Use the answer key's explicit number/answer widths and skip question-option
-- formatting inside it. A key such as "(A),(B),(C)" is a cell value, and
-- the question-option indent would consume most of the cell's text width.
local function Table(tbl)
  local n = #tbl.colspecs
  if n == 0 then return nil end
  if tbl.classes:includes('pl-key-table') then
    for i, spec in ipairs(tbl.colspecs) do
      tbl.colspecs[i] = { pandoc.AlignCenter, spec[2] or (i % 2 == 1 and 0.30 or 0.70) * 2 / n }
    end
    return tbl:walk({ Para = function(p) return pandoc.Plain(p.content) end })
  end
  local key_grid = (n >= 6 and n % 2 == 0)
  for i, spec in ipairs(tbl.colspecs) do
    tbl.colspecs[i] = { key_grid and pandoc.AlignCenter or spec[1], 1 / n }
  end
  return tbl
end

-- ---- pass 2b: option layout ---------------------------------------
-- Approximate visual width (in characters) of a TeX string.
local function tex_width(t)
  local prev
  repeat
    prev = t
    t = t:gsub('\\[dt]?frac%s*(%b{})%s*(%b{})', function(a, b)
      return string.rep('x', math.max(tex_width(a:sub(2, -2)), tex_width(b:sub(2, -2))))
    end)
  until t == prev
  t = t:gsub('\\left', ''):gsub('\\right', ''):gsub('\\[,;:! ]', '')
  t = t:gsub('\\[a-zA-Z]+', 'x'):gsub('[{}^_]', '')
  return utf8.len(t) or #t
end

local function visual_width(inlines)
  local w = 0
  for _, i in ipairs(inlines) do
    if i.t == 'Str' then w = w + (utf8.len(i.text) or #i.text)
    elseif i.t == 'Math' then w = w + tex_width(i.text) + 1
    else w = w + 1 end
  end
  return w
end

local MAX_ROW_WIDTH = 14 -- characters that fit one 101pt option column

local function is_opt(b) return b.t == 'Div' and b.classes:includes('qopt') end

local function opt_inlines(div, with_tab)
  local out = pandoc.List({ pandoc.Strong({ pandoc.Str(div.attributes.label) }) })
  out:insert(with_tab and tab() or pandoc.Space())
  out:extend(div.content[1].content)
  return out
end

local function Blocks(blocks)
  local out = pandoc.List()
  local i = 1
  while i <= #blocks do
    if not is_opt(blocks[i]) then
      out:insert(blocks[i]); i = i + 1
    else
      local group = pandoc.List()
      while i <= #blocks and is_opt(blocks[i]) and #group < 4 do
        group:insert(blocks[i]); i = i + 1
      end
      local fits = #group >= 2
      for _, d in ipairs(group) do
        if visual_width(d.content[1].content) > MAX_ROW_WIDTH then fits = false end
      end
      if fits then
        local inl = pandoc.List({ tab() })
        for k, d in ipairs(group) do
          if k > 1 then inl:insert(tab()) end
          inl:extend(opt_inlines(d, false))
        end
        out:insert(styled('QOptRow', { pandoc.Para(inl) }))
      else
        for _, d in ipairs(group) do
          out:insert(styled('QOpt', { pandoc.Para(opt_inlines(d, false)) }))
        end
      end
    end
  end
  return out
end

-- ---- pass 3 ---------------------------------------------------------
local function roman(n, lower)
  local map = { { 1000, 'M' }, { 900, 'CM' }, { 500, 'D' }, { 400, 'CD' }, { 100, 'C' }, { 90, 'XC' },
    { 50, 'L' }, { 40, 'XL' }, { 10, 'X' }, { 9, 'IX' }, { 5, 'V' }, { 4, 'IV' }, { 1, 'I' } }
  local s = ''
  for _, p in ipairs(map) do
    while n >= p[1] do s = s .. p[2]; n = n - p[1] end
  end
  return lower and s:lower() or s
end

local function alpha(n, lower)
  local c = string.char(64 + ((n - 1) % 26) + 1)
  return lower and c:lower() or c
end

local function label_for(list, n)
  local st = list.style
  local body
  if st == 'LowerRoman' then body = roman(n, true)
  elseif st == 'UpperRoman' then body = roman(n, false)
  elseif st == 'LowerAlpha' then body = alpha(n, true)
  elseif st == 'UpperAlpha' then body = alpha(n, false)
  else body = tostring(n) end
  local d = list.delimiter
  if d == 'OneParen' then return body .. ')' end
  if d == 'TwoParens' then return '(' .. body .. ')' end
  return body .. '.'
end

local function convert_list(list, depth)
  local out = pandoc.List()
  local n = list.start or 1
  local is_bullet = (list.t == 'BulletList')
  for _, item in ipairs(list.content) do
    local label = is_bullet and '•' or label_for(list, n)
    if not is_bullet then n = n + 1 end
    local style = is_bullet and 'QBullet' or (depth == 0 and 'QItem' or 'QSub')
    local cont = depth == 0 and 'QItemCont' or 'QSubCont'
    local first = true
    for _, b in ipairs(item) do
      if b.t == 'OrderedList' or b.t == 'BulletList' then
        out:extend(convert_list(b, depth + 1))
      elseif first and (b.t == 'Para' or b.t == 'Plain') then
        local lab = is_bullet and pandoc.Str(label) or pandoc.Strong({ pandoc.Str(label) })
        local inl = pandoc.List({ lab, tab() })
        inl:extend(b.content)
        out:insert(styled(style, { pandoc.Para(inl) }))
      else
        out:insert(styled(cont, { b }))
      end
      first = false
    end
  end
  return out
end

local function OrderedList(el) return convert_list(el, 0), false end
local function BulletList(el) return convert_list(el, 0), false end

return {
  { Span = Span },
  { Table = Table },
  { Para = Para, Plain = Plain, Figure = Figure },
  { Blocks = Blocks },
  { traverse = 'topdown', OrderedList = OrderedList, BulletList = BulletList },
}
