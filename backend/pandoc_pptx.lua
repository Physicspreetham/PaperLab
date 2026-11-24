-- Paper Builder HTML -> slides: math spans become native PowerPoint equations.
local function Span(el)
  if el.classes:includes('math') then
    local kind = 'InlineMath' -- slides: keep each paragraph whole
    local tex = pandoc.utils.stringify(el)
    tex = tex:gsub('^%s*%^%s*{%s*\\circ%s*}', '°'):gsub('^%s*%^%s*\\circ', '°')
    return pandoc.Math(kind, tex)
  end
end
return { { Span = Span } }
