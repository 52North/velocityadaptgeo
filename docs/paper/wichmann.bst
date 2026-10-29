% wichmann.bst - BibTeX style for the Wichmann Tagungsband (author-year, natbib)
%
% Entry pattern (paper-skill, references/writing-rules.md, "Bibliography"):
%   Surname, I., Surname, I. & Surname, I. (Year): Title. In: Journal, Vol (No), 1-10.
%   Surname, I. (Year): Title. In: Editor, I. (Eds.): Book Title. Place, 23-42.
%   Surname, I. (Year): Title. Place.
%   Surname, I. (Year): Title. https://example.org (11.04.2006).
% Citations: "Name", "Name1 & Name2", "Name et al." (three or more).
% Language-dependent words come from macros defined in paper-style.sty:
%   \bibinname ("In:"), \bibedsname ("(Eds.)"/"(Hrsg.)"), \bibnodatename ("n.d."/"o. J.").

ENTRY
  { address author booktitle doi editor howpublished journal note number
    organization pages publisher title url urldate volume year }
  {}
  { label extra.label }

INTEGERS { nameptr namesleft numnames last.extra.num number.label }

STRINGS { s t n last.label next.extra }

FUNCTION {not}
{ { #0 } { #1 } if$ }

FUNCTION {and}
{ 'skip$ { pop$ #0 } if$ }

FUNCTION {field.or.null}
{ duplicate$ empty$ { pop$ "" } 'skip$ if$ }

% "Vila, M., Martí, M. A. & Rodríguez, H."
FUNCTION {format.names}
{ 's :=
  #1 'nameptr :=
  s num.names$ 'numnames :=
  numnames 'namesleft :=
  "" 't :=
    { namesleft #0 > }
    { s nameptr "{vv~}{ll}{, jj}{, f.}" format.name$ 'n :=
      nameptr #1 >
        { namesleft #1 >
            { t ", " * n * 't := }
            { n "others" =
                { t " et~al." * 't := }
                { t " \& " * n * 't := }
              if$ }
          if$ }
        { n 't := }
      if$
      nameptr #1 + 'nameptr :=
      namesleft #1 - 'namesleft := }
  while$
  t }

% Citation names: "Vila", "Vila \& Martí", "Vila et al."
FUNCTION {format.lab.names}
{ 's :=
  s num.names$ 'numnames :=
  s #1 "{vv~}{ll}" format.name$
  numnames #2 >
    { " et~al." * }
    { numnames #2 =
        { s #2 "{ff }{vv }{ll}{ jj}" format.name$ "others" =
            { " et~al." * }
            { " \& " * s #2 "{vv~}{ll}" format.name$ * }
          if$ }
        'skip$
      if$ }
  if$ }

FUNCTION {lab.names}
{ author empty$ not
    { author format.lab.names }
    { editor empty$ not
        { editor format.lab.names }
        { organization empty$ not { organization } { "Anonymous" } if$ }
      if$ }
  if$ }

FUNCTION {year.or.nodate}
{ year empty$ { "\bibnodatename" } { year } if$ }

FUNCTION {sort.format.names}
{ 's :=
  #1 'nameptr :=
  "" 't :=
  s num.names$ 'numnames :=
  numnames 'namesleft :=
    { namesleft #0 > }
    { s nameptr "{vv{ } }{ll{ }}{  f{ }}{  jj{ }}" format.name$ 'n :=
      t n * "   " * 't :=
      nameptr #1 + 'nameptr :=
      namesleft #1 - 'namesleft := }
  while$
  t }

FUNCTION {sort.names}
{ author empty$ not
    { author sort.format.names }
    { editor empty$ not
        { editor sort.format.names }
        { organization field.or.null }
      if$ }
  if$ }

% label = "Vila et~al.(2014"; extra.label ("a", "b") and ")" are added on output
FUNCTION {presort}
{ lab.names "(" * year.or.nodate * 'label :=
  sort.names "    " * year field.or.null * "    " * title field.or.null *
  purify$ "l" change.case$
  #1 entry.max$ substring$
  'sort.key$ := }

FUNCTION {forward.pass}
{ last.label label =
    { last.extra.num #1 + 'last.extra.num :=
      last.extra.num int.to.chr$ 'extra.label := }
    { "a" chr.to.int$ 'last.extra.num :=
      "" 'extra.label :=
      label 'last.label := }
  if$ }

FUNCTION {reverse.pass}
{ next.extra "b" =
    { "a" 'extra.label := }
    'skip$
  if$
  extra.label 'next.extra := }

FUNCTION {count}
{ number.label #1 + 'number.label := }

% "205--218" -> "205-218" as in the publisher's sample
FUNCTION {single.dash}
{ 't :=
  ""
    { t empty$ not }
    { t #1 #2 substring$ "--" =
        { "-" * t #3 global.max$ substring$ 't := }
        { t #1 #1 substring$ * t #2 global.max$ substring$ 't := }
      if$ }
  while$ }

FUNCTION {format.pages}
{ pages empty$ { "" } { pages single.dash } if$ }

FUNCTION {doi.or.url}
{ doi empty$ not
    { " \url{https://doi.org/" doi * "}" * }
    { url empty$ not
        { " \url{" url * "}" *
          urldate empty$ not { " (" * urldate * ")" * } 'skip$ if$ }
        { "" }
      if$ }
  if$ }

FUNCTION {bibitem.start}
{ newline$
  "\bibitem[{" label * extra.label * ")}]{" * cite$ * "}" * write$
  newline$ }

% "Vila, M. & Martí, M. A. (2014a):"
FUNCTION {author.year.part}
{ author empty$ not
    { author format.names }
    { editor empty$ not
        { editor format.names " \bibedsname" * }
        { organization field.or.null }
      if$ }
  if$
  " (" * year.or.nodate * extra.label * "):" * }

FUNCTION {article}
{ bibitem.start
  author.year.part " " * title add.period$ *
  journal empty$ not
    { " \bibinname{} " * journal *
      volume empty$ not { ", " * volume * } 'skip$ if$
      number empty$ not { " (" * number * ")" * } 'skip$ if$
      pages empty$ not { ", " * format.pages * } 'skip$ if$
      add.period$ }
    'skip$
  if$
  doi.or.url *
  write$ newline$ }

FUNCTION {inproceedings}
{ bibitem.start
  author.year.part " " * title add.period$ *
  " \bibinname{}" *
  editor empty$ not
    { " " * editor format.names * " \bibedsname:" * }
    'skip$
  if$
  booktitle empty$ not { " " * booktitle add.period$ * } 'skip$ if$
  address empty$ not
    { " " * address * }
    { publisher empty$ not { " " * publisher * } 'skip$ if$ }
  if$
  pages empty$ not
    { address empty$ publisher empty$ and
        { " " * format.pages * }
        { ", " * format.pages * }
      if$ }
    'skip$
  if$
  add.period$
  doi.or.url *
  write$ newline$ }

FUNCTION {incollection}
{ inproceedings }

FUNCTION {book}
{ bibitem.start
  author.year.part " " * title add.period$ *
  address empty$ not
    { " " * address add.period$ * }
    { publisher empty$ not { " " * publisher add.period$ * } 'skip$ if$ }
  if$
  doi.or.url *
  write$ newline$ }

FUNCTION {misc}
{ bibitem.start
  author.year.part " " * title add.period$ *
  howpublished empty$ not { " " * howpublished add.period$ * } 'skip$ if$
  note empty$ not { " " * note add.period$ * } 'skip$ if$
  doi.or.url *
  write$ newline$ }

FUNCTION {online}
{ misc }

FUNCTION {default.type}
{ misc }

FUNCTION {begin.bib}
{ preamble$ empty$ 'skip$ { preamble$ write$ newline$ } if$
  "\begin{thebibliography}{" number.label int.to.str$ * "}" * write$
  newline$ }

FUNCTION {end.bib}
{ newline$
  "\end{thebibliography}" write$
  newline$ }

FUNCTION {initialize}
{ "" 'last.label :=
  "" 'next.extra :=
  #0 'number.label := }

READ

EXECUTE {initialize}

ITERATE {presort}

SORT

ITERATE {forward.pass}

REVERSE {reverse.pass}

ITERATE {count}

EXECUTE {begin.bib}

ITERATE {call.type$}

EXECUTE {end.bib}
