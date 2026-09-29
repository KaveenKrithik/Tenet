import curses
import threading
import time
import random
import queue
import sys

def play_snake_while_waiting(request_func, console):
    """
    Runs Snake or Tetris in the main thread.
    `request_func` is a callable: (confirm_callback) -> Result
    It runs in a background thread.
    """
    cmd_queue = queue.Queue()
    result_queue = queue.Queue()
    stop_event = threading.Event()
    game_choice = random.choice(["snake", "tetris"])

    def bg_confirm(est_tokens, tier):
        cmd_queue.put(("confirm", (est_tokens, tier)))
        # Wait for user reply
        reply = cmd_queue.get()
        return reply

    def worker():
        try:
            res = request_func(bg_confirm)
            result_queue.put(("success", res))
        except Exception as e:
            result_queue.put(("error", e))
        finally:
            stop_event.set()
            cmd_queue.put(("done", None))

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    # We loop the game. It can be paused/exited.
    while t.is_alive():
        if stop_event.is_set():
            break

        def game_loop(stdscr):
            curses.curs_set(0)
            stdscr.nodelay(1)
            stdscr.timeout(100)
            
            sh, sw = stdscr.getmaxyx()
            snk_x = sw // 4
            snk_y = sh // 2
            snake = [[snk_y, snk_x], [snk_y, snk_x - 1], [snk_y, snk_x - 2]]
            food = [sh // 2, sw // 2]
            
            try:
                stdscr.addch(food[0], food[1], curses.ACS_PI)
            except curses.error:
                pass
                
            key = curses.KEY_RIGHT
            score = 0
            
            while not stop_event.is_set():
                # Check for commands from background thread
                try:
                    cmd, data = cmd_queue.get_nowait()
                    if cmd == "confirm":
                        # We need to exit curses to prompt user
                        return ("confirm", data)
                    elif cmd == "done":
                        return ("done", None)
                except queue.Empty:
                    pass

                next_key = stdscr.getch()
                key = key if next_key == -1 else next_key
                if key == ord('q'):
                    return ("quit_game", None)

                new_head = [snake[0][0], snake[0][1]]
                if key == curses.KEY_DOWN: new_head[0] += 1
                elif key == curses.KEY_UP: new_head[0] -= 1
                elif key == curses.KEY_LEFT: new_head[1] -= 1
                elif key == curses.KEY_RIGHT: new_head[1] += 1

                snake.insert(0, new_head)

                if snake[0][0] == food[0] and snake[0][1] == food[1]:
                    score += 1
                    food = None
                    while food is None:
                        nf = [random.randint(1, sh - 2), random.randint(1, sw - 2)]
                        food = nf if nf not in snake else None
                    try:
                        stdscr.addch(food[0], food[1], curses.ACS_PI)
                    except curses.error:
                        pass
                else:
                    tail = snake.pop()
                    try:
                        stdscr.addch(tail[0], tail[1], ' ')
                    except curses.error:
                        pass

                try:
                    if (snake[0][0] in [0, sh] or snake[0][1] in [0, sw] or snake[0] in snake[1:]):
                        snake = [[snk_y, snk_x], [snk_y, snk_x-1], [snk_y, snk_x-2]]
                        key = curses.KEY_RIGHT
                        stdscr.clear()
                        stdscr.addch(food[0], food[1], curses.ACS_PI)
                    else:
                        stdscr.addch(snake[0][0], snake[0][1], '#')

                    stdscr.addstr(0, 2, f" Score: {score} | Waiting for Tenet (q to exit game) ")
                except curses.error:
                    pass

            return ("done", None)

        if game_choice == "tetris":
            from tenet.tetris import render_tetris
            try:
                action, data = curses.wrapper(lambda stdscr: render_tetris(stdscr, stop_event, cmd_queue))
            except Exception:
                action, data = "quit_game", None
        else:
            try:
                action, data = curses.wrapper(game_loop)
            except Exception:
                action, data = "quit_game", None

        if action == "confirm":
            import typer
            est_tokens, tier = data
            ans = typer.confirm(f"\n  Estimated {est_tokens:,} tokens ({tier} tier). Escalate?")
            cmd_queue.put(ans)
            # loop continues, curses starts again while waiting
        elif action == "quit_game":
            # user pressed q, show regular spinner until done
            if not stop_event.is_set():
                with console.status("[cyan]Running reduction (game minimized)...[/]", spinner="arc"):
                    while not stop_event.is_set():
                        try:
                            cmd, data = cmd_queue.get(timeout=0.1)
                            if cmd == "confirm":
                                import typer
                                est_tokens, tier = data
                                ans = typer.confirm(f"\n  Estimated {est_tokens:,} tokens ({tier} tier). Escalate?")
                                cmd_queue.put(ans)
                        except queue.Empty:
                            pass
            break

    try:
        status, res = result_queue.get(timeout=1)
        if status == "error":
            raise res
        return res
    except queue.Empty:
        return None

