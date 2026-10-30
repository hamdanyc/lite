#!/usr/bin/env bash
# rm_marker.sh (v3)
# Replace notebook-Gemini citation digits with [cite-marker] and drop 'more_horiz'.
#
#   ./rm_marker.sh                  # Section_*.txt -> Section_*_cleaned.txt
#   ./rm_marker.sh -i               # in place, originals kept as *.bak
#   ./rm_marker.sh a.txt b.txt      # named files
#   MARKER='[C]' ./rm_marker.sh     # custom token
set -uo pipefail

MARKER=${MARKER:-[cite-marker]}
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

export MARKER
for f in "${files[@]}"; do
  [[ -f $f ]] || { printf 'skip (not found): %s\n' "$f" >&2; continue; }
  [[ $f == *_cleaned.txt ]] && { printf 'skip (own output): %s\n' "$f" >&2; continue; }

  if ((backup)); then
    cp -p -- "$f" "$f.bak"
    out=$f
  else
    out="${f%.txt}_cleaned.txt"        # a.txt -> a_cleaned.txt
  fi

  perl -pe '
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
  ' -- "$f" > "$out.tmp" || { echo "perl failed on $f" >&2; rm -f -- "$out.tmp"; continue; }
  mv -- "$out.tmp" "$out"

  printf '%-28s -> %-38s %3s markers, %s more_horiz left\n' "$f" "$out" \
    "$(grep -oF -- "$MARKER" "$out" | wc -l | tr -d ' ')" \
    "$(grep -o more_horiz "$out" | wc -l | tr -d ' ')"
done
