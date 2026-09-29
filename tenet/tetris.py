import curses
import random
import time

SHAPES = [
    [[1, 1, 1, 1]],
    [[1, 1], [1, 1]],
    [[0, 1, 0], [1, 1, 1]],
    [[1, 0, 0], [1, 1, 1]],
    [[0, 0, 1], [1, 1, 1]],
    [[1, 1, 0], [0, 1, 1]],
    [[0, 1, 1], [1, 1, 0]]
]

class Tetris:
    def __init__(self, height=20, width=10):
        self.height = height
        self.width = width
        self.board = [[0]*width for _ in range(height)]
        self.score = 0
        self.game_over = False
        self.new_piece()
        
    def new_piece(self):
        self.piece = random.choice(SHAPES)
        self.piece_y = 0
        self.piece_x = self.width // 2 - len(self.piece[0]) // 2
        
        if self.check_collision(self.piece, self.piece_y, self.piece_x):
            self.game_over = True
            
    def check_collision(self, piece, y, x):
        for r, row in enumerate(piece):
            for c, val in enumerate(row):
                if val:
                    if (y + r >= self.height or
                        x + c < 0 or
                        x + c >= self.width or
                        self.board[y + r][x + c]):
                        return True
        return False
        
    def merge_piece(self):
        for r, row in enumerate(self.piece):
            for c, val in enumerate(row):
                if val:
                    self.board[self.piece_y + r][self.piece_x + c] = 1
        
        # clear lines
        new_board = [row for row in self.board if not all(row)]
        cleared = self.height - len(new_board)
        self.score += cleared * 10
        self.board = [[0]*self.width for _ in range(cleared)] + new_board
        
        self.new_piece()

    def move(self, dy, dx):
        if not self.check_collision(self.piece, self.piece_y + dy, self.piece_x + dx):
            self.piece_y += dy
            self.piece_x += dx
            return True
        elif dy == 1: # hit bottom
            self.merge_piece()
        return False
        
    def rotate(self):
        new_piece = list(zip(*self.piece[::-1]))
        if not self.check_collision(new_piece, self.piece_y, self.piece_x):
            self.piece = new_piece

def render_tetris(stdscr, stop_event, cmd_queue):
    curses.curs_set(0)
    stdscr.nodelay(1)
    stdscr.timeout(200) # Faster/slower based on level?
    
    sh, sw = stdscr.getmaxyx()
    
    # Calculate offset to center the board
    board_h, board_w = 20, 10
    start_y = (sh - board_h) // 2
    start_x = (sw - board_w * 2) // 2
    
    if start_y < 0 or start_x < 0:
        stdscr.addstr(0, 0, "Terminal too small for Tetris")
        stdscr.refresh()
        time.sleep(2)
        return "done", None

    game = Tetris(board_h, board_w)
    
    last_drop = time.time()
    
    while not stop_event.is_set():
        if not cmd_queue.empty():
            cmd, data = cmd_queue.get_nowait()
            if cmd == "confirm":
                return "confirm", data
            elif cmd == "done":
                return "done", None

        if game.game_over:
            game = Tetris(board_h, board_w)
            
        key = stdscr.getch()
        if key == ord('q'):
            return "quit_game", None
            
        if key == curses.KEY_LEFT:
            game.move(0, -1)
        elif key == curses.KEY_RIGHT:
            game.move(0, 1)
        elif key == curses.KEY_DOWN:
            game.move(1, 0)
        elif key == curses.KEY_UP:
            game.rotate()
            
        if time.time() - last_drop > 0.5:
            game.move(1, 0)
            last_drop = time.time()
            
        stdscr.clear()
        
        # Draw border
        for y in range(board_h + 2):
            try:
                stdscr.addstr(start_y + y - 1, start_x - 2, "<!")
                stdscr.addstr(start_y + y - 1, start_x + board_w * 2, "!>")
            except curses.error:
                pass
        
        # Draw board
        for r, row in enumerate(game.board):
            for c, val in enumerate(row):
                if val:
                    try:
                        stdscr.addstr(start_y + r, start_x + c * 2, "[]")
                    except curses.error:
                        pass
                        
        # Draw piece
        for r, row in enumerate(game.piece):
            for c, val in enumerate(row):
                if val:
                    try:
                        stdscr.addstr(start_y + game.piece_y + r, start_x + (game.piece_x + c) * 2, "[]")
                    except curses.error:
                        pass
                        
        try:
            stdscr.addstr(0, 2, f" TETRIS | Score: {game.score} | (q to exit) ")
        except curses.error:
            pass
            
        stdscr.refresh()
        
    return "done", None
