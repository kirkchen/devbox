# Gitpod Environment Management
# Interactive Gitpod environment management with fzf integration

gpenv() {
  local action="$1"
  
  case "$action" in
    start)
      local env_id=$(gitpod env list | grep -v "^ID" | grep -E "(stopped|stopping)" | fzf --prompt="Select environment to start: " | awk '{print $1}')
      if [[ -n "$env_id" ]]; then
        echo "Starting: $env_id"
        gitpod env start "$env_id"
        
        # Default Y, press enter to connect
        echo "SSH to environment? (Y/n)"
        read -r choice
        if [[ "$choice" != "n" && "$choice" != "N" ]]; then
          gitpod env ssh "$env_id"
        fi
      fi
      ;;
      
    stop)
      local env_id=$(gitpod env list | grep -v "^ID" | grep "running" | fzf --prompt="Select environment to stop: " | awk '{print $1}')
      if [[ -n "$env_id" ]]; then
        echo "Stopping: $env_id"
        gitpod env stop "$env_id"
      fi
      ;;
      
    ssh)
      local env_id=$(gitpod env list | grep -v "^ID" | grep "running" | fzf --prompt="Select environment to SSH: " | awk '{print $1}')
      if [[ -n "$env_id" ]]; then
        gitpod env ssh "$env_id"
      fi
      ;;
      
    open)
      local env_id=$(gitpod env list | grep -v "^ID" | grep "running" | fzf --prompt="Select environment to open: " | awk '{print $1}')
      if [[ -n "$env_id" ]]; then
        gitpod env open "$env_id"
      fi
      ;;
      
    list|ls)
      gitpod env list
      ;;
      
    *)
      echo "Usage: gpenv {start|stop|ssh|open|list}"
      echo ""
      echo "Commands:"
      echo "  start  - Start a stopped environment and optionally SSH into it"
      echo "  stop   - Stop a running environment"
      echo "  ssh    - SSH into a running environment"
      echo "  open   - Open a running environment in browser"
      echo "  list   - List all environments"
      ;;
  esac
}

# Gitpod shortcuts
alias gps='gpenv start'   # Start stopped environment
alias gpt='gpenv stop'    # Stop running environment  
alias gpsh='gpenv ssh'    # SSH into running environment
alias gpo='gpenv open'    # Open in browser
alias gpl='gpenv list'    # List all environments