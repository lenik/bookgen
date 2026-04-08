_bookgen_completions()
{
    local cur prev
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    local opts="-S --service -t --type -m --model -C --context -o --outdir -s --summary-size -n --chapter -c --chapter-format -l --lang -e --echo -v --verbose -q --quiet -h --help --version"

    case "${prev}" in
        -t|--type)
            COMPREPLY=( $(compgen -W "ollama openai" -- "${cur}") )
            return 0
            ;;
    esac

    if [[ "${cur}" == -* ]]; then
        COMPREPLY=( $(compgen -W "${opts}" -- "${cur}") )
        return 0
    fi

    COMPREPLY=( $(compgen -f -- "${cur}") )
}

complete -F _bookgen_completions bookgen
