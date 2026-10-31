#!/usr/bin/env bash
# rm_marker_deep.sh (v4)
# v3 : drop the 'more_horiz' scraper artifact, turn notebook-Gemini citation
#      digits into [cite-marker] while protecting real numbers (p-values,
#      percentages, years, section numbers, H1/H2 labels).
# v4 : layout pass - three new rules
#      (a) exactly HEAD_NL newlines in front of every numbered heading
#          (1.1 , 1.1.2 , 1.2.4 ...), whether it is glued to the preceding
#          word ("AIEd1.1 Rational ...") or already starts a line;
#      (b) every ALL-CAPS ASCII-figure caption is isolated on its own block:
#          CAP_NL newlines before it, CAP_NL newlines after it;
#      (c) the "==========" underline that sat under each caption is deleted
#          (any remaining all-'=' rule line too).
#
#   ./rm_marker_deep.sh                     # Section_*.txt -> Section_*_Cleaned.txt
#   ./rm_marker_deep.sh -i                  # in place, originals kept as *.bak
#   ./rm_marker_deep.sh a.txt b.txt         # named files
#   MARKER='[C]' ./rm_marker_deep.sh        # custom citation token
#   HEAD_NL=3 CAP_NL=3 ./rm_marker_deep.sh  # two blank lines instead of one
set -uo pipefail

MARKER=${MARKER:-[cite-marker]}
HEAD_NL=${HEAD_NL:-2}          # 2 -> one blank line before a heading
CAP_NL=${CAP_NL:-2}            # 2 -> one blank line around a caption

backup=0; args=()
for a in "$@"; do
  case $a in
    -i|--in-place) backup=1 ;;
    *)             args+=("$a") ;;
  esac
done

if ((${#args[@]})); then files=("${args[@]}")
else shopt -s nullglob; files=(Section_*.txt); fi
((${#files[@]})) || { echo "no input files" >&2; exit 1; }

export MARKER HEAD_NL CAP_NL
for f in "${files[@]}"; do
  [[ -f $f ]] || { printf 'skip (not found): %s\n' "$f" >&2; continue; }
  [[ $f == *_cleaned.txt || $f == *_Cleaned.txt ]] \
    && { printf 'skip (own output): %s\n' "$f" >&2; continue; }

  if ((backup)); then
    cp -p -- "$f" "$f.bak"
    out=$f
  else
    out="${f%.txt}_Cleaned.txt"        # a.txt -> a_Cleaned.txt
  fi

  # -0777 = slurp: the layout rules need to see across line boundaries
  perl -0777 -pe '
    # ---------- separators used by the layout pass ----------
    $H = "\n" x ($ENV{HEAD_NL} || 2);
    $C = "\n" x ($ENV{CAP_NL}  || 2);

    # ============== PASS 1 : citation markers (v3, unchanged) ==============
    # 1) scraper artifact, plus any blanks glued to it, disappears first
    s/[ \t]*more_horiz(?![A-Za-z0-9_])//g;

    # 2) one pass.  Keep-list branches echo themselves back ($+{keep} defined);
    #    the trailing branch has no capture, so it substitutes the token.
    #    NOTE: that branch MUST stay outside (?<keep>) -- moving it inside
    #    turns every citation into a no-op.
    s{(?<keep>
         \d+\s*/\s*\d+                                        # 24/7
       | \d+(?:\.\d+)?\s*%                                    # 8%  13.72%
       | (?<=[^\w\d]) \d{1,3}(?:\.\d{1,3}){1,2} (?![\d.])     # 1.1  1.2.4
       | (?<=[A-Za-z]) \d     (?:\.\d{1,3}){1,2} (?![\d.])    # AIEd1.1
       | (?<!\w)(?:19|20)\d{2}(?!\d)                          # 2024
      )
       | (?<=[^\s\d=:]) \d+                                   # citation digits,
       | (?<![A-Za-z])[A-Z]\d{1,2}(?![\w])                    # H1  H2  T3
     }{ defined $+{keep} ? $+{keep} : $ENV{MARKER} }gxe;      # never N=6837

    # ============== PASS 2 : figure captions ==============================
    # A caption = an ALL-CAPS run that ends a line which is immediately
    # followed by a line made only of "=".  Re-emitted as
    #     <text before it> \n\n <indentation><CAPTION> \n\n
    # so the "=" underline is swallowed (deleted) here.
    s{ ^ (?<pre> .*? ) (?<ind> [ \t]+ )
       (?<cap> [A-Z] (?: [A-Z0-9] | [^a-zA-Z0-9\n] )*? )
       [ \t]* \n [ \t]* =+ [ \t]* \n (?: [ \t]* \n )?
     }{
       ( length($+{pre}) ? $+{pre} . $C
                         : ($-[0] ? ("\n" x (($ENV{CAP_NL} || 2) - 1)) : "") )
       . $+{ind} . $+{cap} . $C
     }gmxe;

    # ============== PASS 3 : any surviving "=" rule lines =================
    s{ ^ [ \t]* =+ [ \t]* \n }{}gmx;

    # ============== PASS 4 : numbered headings ============================
    # 1.1 / 1.1.2 ... reached glued to text ("AIEd1.1", "...[cite-marker].1.2")
    # or already at line start (after a figure block) -> normalised to exactly
    # HEAD_NL newlines, with no duplicate blank lines either way.
    s{ (?<! \d ) (?<! \d\. ) [ \t]* \n* [ \t]*
       ( \d{1,2} (?:\.\d{1,2}){1,2} ) (?= [ \t]+ [A-Z] )
     }{ $H . $1 }gxe;
  ' -- "$f" > "$out.tmp" || { echo "perl failed on $f" >&2; rm -f -- "$out.tmp"; continue; }
  mv -- "$out.tmp" "$out"

  printf '%-28s -> %-38s %3s markers, %s more_horiz left, %s "=" rules left\n' \
    "$f" "$out" \
    "$(grep -oF -- "$MARKER" "$out" | wc -l | tr -d ' ')" \
    "$(grep -o more_horiz "$out" | wc -l | tr -d ' ')" \
    "$(grep -cE '^[[:space:]]*=+[[:space:]]*$' "$out" | tr -d ' ')"
done
