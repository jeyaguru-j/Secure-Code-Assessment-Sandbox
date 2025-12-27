import sys
import random

class BefungeInterpreter:
    def __init__(self):
        self.stack = []
        self.grid = []
        self.width = 80
        self.height = 25
        self.pc = [0, 0]
        self.delta = [1, 0]
        self.string_mode = False
        self.output = []      # CHANGED: Buffer for output
        self.input_data = ""  # CHANGED: Buffer for input
        self.input_ptr = 0    # CHANGED: Pointer for input reading

    def load_code(self, code_string):
        lines = code_string.split('\n')
        self.grid = []
        for y in range(self.height):
            row = []
            line = lines[y] if y < len(lines) else ""
            for x in range(self.width):
                char = line[x] if x < len(line) else " "
                row.append(ord(char))
            self.grid.append(row)

    def pop(self):
        if not self.stack: return 0
        return self.stack.pop()

    def push(self, value):
        self.stack.append(value)

    def step(self):
        x, y = self.pc
        op = self.grid[y][x]
        char = chr(op)

        if self.string_mode:
            if char == '"': self.string_mode = False
            else: self.push(op)
        else:
            if char == '>': self.delta = [1, 0]
            elif char == '<': self.delta = [-1, 0]
            elif char == '^': self.delta = [0, -1]
            elif char == 'v': self.delta = [0, 1]
            elif char == '_': self.delta = [1, 0] if self.pop() == 0 else [-1, 0]
            elif char == '|': self.delta = [0, 1] if self.pop() == 0 else [0, -1]
            elif char == '?': self.delta = random.choice([[1,0], [-1,0], [0,1], [0,-1]])
            elif char == '+': self.push(self.pop() + self.pop())
            elif char == '-': 
                a, b = self.pop(), self.pop()
                self.push(b - a)
            elif char == '*': self.push(self.pop() * self.pop())
            elif char == '/': 
                a, b = self.pop(), self.pop()
                self.push(0 if a == 0 else b // a)
            elif char == '%': 
                a, b = self.pop(), self.pop()
                self.push(0 if a == 0 else b % a)
            elif char == '!': self.push(1 if self.pop() == 0 else 0)
            elif char == '`': 
                a, b = self.pop(), self.pop()
                self.push(1 if b > a else 0)
            elif char == ':': 
                val = self.pop()
                self.push(val)
                self.push(val)
            elif char == '\\': 
                a, b = self.pop(), self.pop()
                self.push(a) 
                self.push(b)
            elif char == '$': self.pop()
            elif char == '.': self.output.append(str(self.pop()) + " ") # CHANGED
            elif char == ',': self.output.append(chr(self.pop()))       # CHANGED
            elif char == '#': 
                self.pc[0] = (self.pc[0] + self.delta[0]) % self.width
                self.pc[1] = (self.pc[1] + self.delta[1]) % self.height
            elif char == 'g': 
                y, x = self.pop(), self.pop()
                if 0 <= x < self.width and 0 <= y < self.height: self.push(self.grid[y][x])
                else: self.push(0)
            elif char == 'p': 
                y, x, v = self.pop(), self.pop(), self.pop()
                if 0 <= x < self.width and 0 <= y < self.height: self.grid[y][x] = v
            elif char == '&': # CHANGED: Handle Numeric Input
                try:
                    # Very basic input parser: find next number in string
                    remaining = self.input_data[self.input_ptr:].strip()
                    num_str = ""
                    for c in remaining:
                        if c.isdigit() or (c == '-' and not num_str): num_str += c
                        elif num_str: break
                    if num_str:
                         self.push(int(num_str))
                         # Advance ptr roughly (naive implementation)
                         self.input_ptr += self.input_data[self.input_ptr:].find(num_str) + len(num_str)
                    else: self.push(0)
                except: self.push(0)
            elif char == '~': # CHANGED: Handle Char Input
                try:
                    if self.input_ptr < len(self.input_data):
                        self.push(ord(self.input_data[self.input_ptr]))
                        self.input_ptr += 1
                    else: self.push(-1)
                except: self.push(0)
            elif char == '"': self.string_mode = True
            elif char == '@': return False
            elif char.isdigit(): self.push(int(char))

        self.pc[0] = (self.pc[0] + self.delta[0]) % self.width
        self.pc[1] = (self.pc[1] + self.delta[1]) % self.height
        return True

    def run(self, code, input_str="", tick_limit=100000):
        self.load_code(code)
        self.input_data = input_str
        self.input_ptr = 0
        self.output = []
        
        running = True
        steps = 0
        while running and steps < tick_limit:
            running = self.step()
            steps += 1
        
        if steps >= tick_limit:
            return "".join(self.output) + "\n[Error: Time Limit Exceeded]"
            
        return "".join(self.output)