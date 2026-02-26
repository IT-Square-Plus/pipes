#!/bin/bash

# Colors for better output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# Print header
print_header() {
    echo -e "${CYAN}🔍 Gitleaks Security Scanner${NC}"
}

# Print success message
print_success() {
    echo ""
    echo -e "${GREEN}✅ CLEAN: No secrets detected!${NC}"
    echo -e "${GREEN}🛡️  Security Status: PASSED${NC}"
}

# Print detailed report
print_detailed_report() {
    local report_file="$1"
    local total_issues="$2"
    local strip_prefix="$3"

    echo -e "${RED}❌ FOUND $total_issues SECURITY ISSUE(S):${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Print each issue with detailed formatting (strip base path for readability)
    jq -r --arg prefix "$strip_prefix" 'to_entries[] |
    "🚨 ISSUE #" + (.key + 1 | tostring) + "
" +
    "  RuleID:       " + .value.RuleID + "
  Description:  " + .value.Description + "
  StartLine:    " + (.value.StartLine | tostring) + "
  EndLine:      " + (.value.EndLine | tostring) + "
  StartColumn:  " + (.value.StartColumn | tostring) + "
  EndColumn:    " + (.value.EndColumn | tostring) + "
  Match:        " + (.value.Match // "N/A") + "
  Secret:       " + (.value.Secret // "N/A") + "
  File:         " + (.value.File | ltrimstr($prefix)) + "
  SymlinkFile:  " + (.value.SymlinkFile // "") + "
  Commit:       " + (.value.Commit // "") + "
  Entropy:      " + (.value.Entropy | tostring) + "
  Author:       " + (.value.Author // "") + "
  Email:        " + (.value.Email // "") + "
  Date:         " + (.value.Date // "") + "
  Message:      " + (.value.Message // "") + "
  Tags:         " + ((.value.Tags // []) | join(", ")) + "
  Fingerprint:  " + (.value.Fingerprint | ltrimstr($prefix) // "N/A") + "

  ➡️  " + (.value.File | ltrimstr($prefix)) + ":" + (.value.StartLine | tostring) + "
  🏷️  " + .value.Description + "
  🔑  " + (.value.Secret // "N/A") + "
  " + (if (.value.RuleID | startswith("glcr-")) then "✏️  Custom Rules" else "📦  Gitleaks Library" end) + "

────────────────────────────────────────────────────────────"' "$report_file"

    echo ""
    echo -e "${PURPLE}📋 SUMMARY: $total_issues issue(s) in the following files:${NC}"
    jq -r --arg prefix "$strip_prefix" 'group_by(.File) | .[] | "   • " + (.[0].File | ltrimstr($prefix)) + " (" + (length | tostring) + " issue(s))"' "$report_file"
}

# Main script
main() {
    print_header

    EXIT_CODE=0
    REPORT_FILE="gitleaks-report.json"

    # Run gitleaks - scan only the main repo, not the templates library
    CONFIG_PATH="${BUILD_SOURCESDIRECTORY:-$(pwd)}/14494_CMMN_EMEA-GI-Team-Common-Library/pipeline-modules/dotfiles/.gitleaks.custom.toml"
    MAIN_REPO=$(ls -d "${BUILD_SOURCESDIRECTORY:-$(pwd)}"/*/ | grep -v "14494_CMMN_EMEA-GI-Team-Common-Library" | head -1)

    if [ -z "$MAIN_REPO" ]; then
        MAIN_REPO="${BUILD_SOURCESDIRECTORY:-$(pwd)}"
    fi

    echo -e "${BLUE}Scanning: $MAIN_REPO${NC}"
    gitleaks detect --config "$CONFIG_PATH" --source "$MAIN_REPO" --no-git --verbose --redact=25 \
        --report-path "$REPORT_FILE" --report-format json || EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        print_success
    else
        if command -v jq &> /dev/null && [ -f "$REPORT_FILE" ]; then
            TOTAL=$(jq length "$REPORT_FILE")
            STRIP_PREFIX="${BUILD_SOURCESDIRECTORY:-$(pwd)}/"
            print_detailed_report "$REPORT_FILE" "$TOTAL" "$STRIP_PREFIX"
            echo -e "${RED}Security scan failed - full report available as pipeline artifact${NC}"
        else
            echo -e "${RED}❌ Security scan failed but unable to parse results${NC}"
            if [ ! -f "$REPORT_FILE" ]; then
                echo -e "${YELLOW}⚠️  Report file not found: $REPORT_FILE${NC}"
            fi
            if ! command -v jq &> /dev/null; then
                echo -e "${YELLOW}⚠️  jq not installed - install with: brew install jq${NC}"
            fi
        fi
        exit 1
    fi
}

# Run main function
main "$@"
