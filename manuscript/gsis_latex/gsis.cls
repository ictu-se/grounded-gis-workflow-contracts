\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{gsis}[2026/06/29 Local compatibility class for manuscript submissions]

% Local compatibility class that keeps the template interface (\Abstract,
% \keywords, \copyrightyear, \datereceived, \dateaccepted, \author[a], and
% \affil[a]) buildable locally.

\LoadClass[12pt]{article}

\RequirePackage{authblk}
\RequirePackage{geometry}
\RequirePackage{fancyhdr}
\RequirePackage{titlesec}
\RequirePackage{caption}
\RequirePackage{xcolor}
\RequirePackage{hyperref}

\geometry{a4paper,top=25mm,bottom=25mm,left=25mm,right=25mm}
\setlength{\headheight}{15pt}
\setlength{\emergencystretch}{3em}
\setlength{\parindent}{0pt}
\setlength{\parskip}{6pt}

\newcommand{\@copyrightyear}{}
\newcommand{\@datereceived}{}
\newcommand{\@dateaccepted}{}
\newcommand{\@abstracttext}{}
\newcommand{\@keywordstext}{}

\newcommand{\copyrightyear}[1]{\gdef\@copyrightyear{#1}}
\newcommand{\datereceived}[1]{\gdef\@datereceived{#1}}
\newcommand{\dateaccepted}[1]{\gdef\@dateaccepted{#1}}
\newcommand{\Abstract}[1]{\gdef\@abstracttext{#1}}
\newcommand{\keywords}[1]{\gdef\@keywordstext{#1}}

\renewcommand\Authfont{\normalsize}
\renewcommand\Affilfont{\small}
\setlength{\affilsep}{0.4em}

\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{Workflow Contracts for GIS Copilots}
\fancyhead[R]{\thepage}
\renewcommand{\headrulewidth}{0.4pt}

\titleformat{\section}{\normalfont\large\bfseries}{\thesection}{0.75em}{}
\titleformat{\subsection}{\normalfont\normalsize\bfseries}{\thesubsection}{0.75em}{}
\titleformat{\subsubsection}{\normalfont\normalsize\itshape}{\thesubsubsection}{0.75em}{}

\captionsetup{font=small,labelfont=bf}

\let\gsis@oldmaketitle\maketitle
\renewcommand{\maketitle}{%
  \begin{center}
    {\LARGE\bfseries \@title\par}
    \vspace{1em}
    {\@author\par}
  \end{center}
  \vspace{0.5em}
  \ifx\@datereceived\@empty\else
    {\small Received: \@datereceived\quad Accepted: \@dateaccepted\par}
  \fi
  \vspace{1em}
  \noindent\textbf{Abstract}\quad \@abstracttext\par
  \vspace{0.75em}
  \noindent\textbf{Keywords:} \@keywordstext\par
  \vspace{1.25em}
}

\newtheorem{Theorem}{Theorem}
\newenvironment{proof}[1][Proof]{\par\noindent\textit{#1.}\ }{\hfill$\square$\par}
