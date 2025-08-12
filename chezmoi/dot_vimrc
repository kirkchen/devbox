" compatible with vi
set nocompatible
filetype off                  " required

" Install vim-plug if not found
if empty(glob('~/.vim/autoload/plug.vim'))
  silent !curl -fLo ~/.vim/autoload/plug.vim --create-dirs
    \ https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim
endif

" Run PlugInstall if there are missing plugins
autocmd VimEnter * if len(filter(values(g:plugs), '!isdirectory(v:val.dir)'))
  \| PlugInstall --sync | source $MYVIMRC
\| endif

" Vim plugins (via Vim-plug)
call plug#begin('~/.vim/bundle')

" Vim Color Schema
Plug 'sainnhe/sonokai'
" Vim File Explorer
Plug 'scrooloose/nerdtree'
" Vim Status bar
Plug 'vim-airline/vim-airline'
Plug 'vim-airline/vim-airline-themes'
" Vim Easymotion
Plug 'Lokaltog/vim-easymotion'
" Vim Search
Plug 'junegunn/fzf'
Plug 'junegunn/fzf.vim'
" Vim comment
Plug 'scrooloose/nerdcommenter'
" Vim multi selector
Plug 'terryma/vim-multiple-cursors'
" Vim surround
Plug 'tpope/vim-surround'

" Autocomplete
Plug 'neoclide/coc.nvim', {'branch': 'release'}

" Git
Plug 'tpope/vim-fugitive'
Plug 'airblade/vim-gitgutter'

" Rails
Plug 'vim-ruby/vim-ruby'
Plug 'tpope/vim-rails'

" Html
Plug 'mattn/emmet-vim'
Plug 'othree/html5.vim'
Plug 'othree/yajs.vim'
Plug 'othree/es.next.syntax.vim'
Plug 'joukevandermaas/vim-ember-hbs'

" Linting
Plug 'dense-analysis/ale'

" Testing
Plug 'vim-test/vim-test'

" All of your Plugins must be added before the following line
call plug#end()

" show line number
set number relativenumber

" show syntax highlight
syntax on

set showmatch

set encoding=utf-8

set tabstop=2
set softtabstop=2
set shiftwidth=2
set expandtab

set nobackup
set noswapfile

set hlsearch

set guitablabel=%t

let mapleader = ','

" Theme
if has('termguicolors')
  set termguicolors
endif
" The configuration options should be placed before `colorscheme sonokai`.
let g:sonokai_style = 'maia'
let g:sonokai_better_performance = 1
colorscheme sonokai

let g:airline_theme = 'sonokai'

" Highlight trailing whitespaces
highlight ExtraWhitespace ctermbg=red guibg=red
match ExtraWhitespace /\s\+$/
autocmd BufWinEnter * match ExtraWhitespace /\s\+$/
autocmd InsertEnter * match ExtraWhitespace /\s\+\%#\@<!$/
autocmd InsertLeave * match ExtraWhitespace /\s\+$/
autocmd BufWinLeave * call clearmatches()

" ,/ turn off search highlighting
nmap <leader>/ :nohl<CR>

" ,p toggles paste mode
nmap <leader>p :set paste!<BAR>set paste?<CR>

" Airline settings
set laststatus=2
let g:airline_powerline_fonts = 1
let g:airline_theme='molokai'
let g:airline#extensions#tabline#enabled = 1

" fzf settings
" - Popup window (center of the screen)
let g:fzf_layout = { 'window': { 'width': 0.9, 'height': 0.8 } }
nmap <C-p> :Files<CR>
nmap <leader>b :Buffers<CR>
nmap <leader>f :Ag<CR>

" Easymotion
let g:EasyMotion_do_mapping = 0
map <leader>s <Plug>(easymotion-s2)

" NERDTree settings
nmap <F2> :NERDTreeToggle<CR>

" NERDComment settings
let g:NERDSpaceDelims=1

" Ruby
"let g:tagbar_type_ruby = {
"    \ 'ctagstype' : 'Ruby',
"    \ 'kinds'     : [
"        \ 'c:classes',
"        \ 'f:methods',
"        \ 'F:singleton methods',
"        \ 'm:modules',
"        \ 'n:namespaces',
"        \ 't:tasks'
"    \ ]
"	\ }

" Vim auto align settings
" Start interactive EasyAlign in visual mode (e.g. vipga)
"xmap ga <Plug>(EasyAlign)
" Start interactive EasyAlign for a motion/text object (e.g. gaip)
"nmap ga <Plug>(EasyAlign)

" Map capistrano file type
"au BufNewFile,BufRead *.cap set filetype=ruby

" Map jenkins file type
"au BufNewFile,BufRead Jenkinsfile set filetype=groovy
"au BufNewFile,BufRead JenkinsfileDeploy set filetype=groovy

" Prettier
let g:ale_linters = {
\  'javascript': ['eslint'],
\  'ruby': ['rubocop'],
\}
let g:ale_fixers = {
\ 'javascript': ['prettier'],
\ 'scss': ['prettier'],
\ 'handlebars': ['prettier'],
\ 'ruby': ['rubocop'],
\}
" Format on Save
let g:ale_fix_on_save = 1
let g:ale_ruby_rubocop_executable = 'bundle'

" CoC
let g:coc_global_extensions = [
\ 'coc-tsserver',
\ 'coc-prettier',
\ 'coc-eslint',
\ 'coc-solargraph',
\ 'coc-html',
\ 'coc-css',
\ 'coc-json',
\ 'coc-ember',
\ 'coc-highlight',
\]
" Use tab for trigger completion with characters ahead and navigate.
inoremap <silent><expr> <TAB>
      \ pumvisible() ? "\<C-n>" :
      \ CheckBackspace() ? "\<TAB>" :
      \ coc#refresh()
inoremap <expr><S-TAB> pumvisible() ? "\<C-p>" : "\<C-h>"
" Make <CR> auto-select the first completion item and notify coc.nvim to
" format on enter, <cr> could be remapped by other vim plugin
inoremap <silent><expr> <cr> pumvisible() ? coc#_select_confirm()
                              \: "\<C-g>u\<CR>\<c-r>=coc#on_enter()\<CR>"
" Use `[g` and `]g` to navigate diagnostics
" Use `:CocDiagnostics` to get all diagnostics of current buffer in location list.
nmap <silent> [g <Plug>(coc-diagnostic-prev)
nmap <silent> ]g <Plug>(coc-diagnostic-next)
" GoTo code navigation.
nmap <silent> gd <Plug>(coc-definition)
nmap <silent> gy <Plug>(coc-type-definition)
nmap <silent> gi <Plug>(coc-implementation)
nmap <silent> gr <Plug>(coc-references)

" Testing
nmap <silent> <leader>tt :TestNearest<CR>
nmap <silent> <leader>tT :TestFile<CR>
nmap <silent> <leader>ta :TestSuite<CR>
nmap <silent> <leader>tl :TestLast<CR>
nmap <silent> <leader>tg :TestVisit<CR>

" Remove trailing white spaces
function StripTrailingWhitespace()
  if !&binary && &filetype != 'diff'
    normal mz
    normal Hmy
    %s/\s\+$//e
    normal 'yz<CR>
    normal `z
  endif
endfunction
