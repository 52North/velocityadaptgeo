% paper.cls - document class for the Tagungsband layout (template/Mustertext_Tagungsband.docx)
% Sets the font (Times New Roman / Liberation Serif) and makes article.cls load without
% Latin Modern, fixes 10 pt + two-sided layout and loads paper-style.sty with all formatting.
% Usage: \documentclass{paper} or \documentclass[ngerman]{paper}
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{paper}[2026/10/29 Tagungsband layout]

\DeclareOption{ngerman}{\PassOptionsToPackage{ngerman}{paper-style}}
\DeclareOption*{\ClassWarning{paper}{Unknown option '\CurrentOption'}}
\ProcessOptions\relax

% article.cls selects Latin Modern (TU/lmr) while it loads. Where Latin Modern is not
% installed, point that family at Liberation Serif so loading does not fail.
\ifdefined\directlua
  \IfFileExists{lmroman10-regular.otf}{}{%
    \DeclareFontFamily{TU}{lmr}{}%
    \DeclareFontShape{TU}{lmr}{m}{n}{<->file:LiberationSerif-Regular.ttf:+tlig;}{}%
    \DeclareFontShape{TU}{lmr}{m}{it}{<->file:LiberationSerif-Italic.ttf:+tlig;}{}%
    \DeclareFontShape{TU}{lmr}{bx}{n}{<->file:LiberationSerif-Bold.ttf:+tlig;}{}%
    \DeclareFontShape{TU}{lmr}{bx}{it}{<->file:LiberationSerif-BoldItalic.ttf:+tlig;}{}%
    \DeclareFontShape{TU}{lmr}{b}{n}{<->ssub * lmr/bx/n}{}%
    \DeclareFontShape{TU}{lmr}{b}{it}{<->ssub * lmr/bx/it}{}}
\fi

\LoadClass[10pt,twoside]{article}

% Font: Times New Roman if installed, else the metric-identical Liberation Serif
% (LuaLaTeX only; pdfLaTeX falls back inside paper-style.sty)
\ifdefined\directlua
  \RequirePackage{fontspec}
  \IfFontExistsTF{Times New Roman}
    {\setmainfont{Times New Roman}}
    {\setmainfont{Liberation Serif}}
  \IfFontExistsTF{Arial}
    {\setsansfont{Arial}}
    {\setsansfont{Liberation Sans}}
  \IfFontExistsTF{Courier New}
    {\setmonofont{Courier New}}
    {\setmonofont{Liberation Mono}}
\fi

\RequirePackage{paper-style}

\endinput
