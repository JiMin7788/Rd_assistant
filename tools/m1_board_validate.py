"""Validate the full board reader (type + per-theme pip) on the target-deck
frame. Ground truth from visual inspection of session _0747_ab15 f7000."""
import numpy as np
from PIL import Image
from rdom.perception.board import read_board

TRUTH_T = {1:'Predator',2:'Light',3:'Predator',4:'Bubble',5:'Resonance',
           6:'Light',7:'Light',8:'Light',9:'Light',10:'Resonance',
           11:'Predator',12:'Light',13:'Bubble',14:'Resonance',15:'Resonance'}
TRUTH_P = {1:1,2:1,3:1,4:1,5:1,6:1,7:2,8:1,9:1,10:1,11:1,12:1,13:2,14:1,15:1}

img = np.array(Image.open(r'C:\dev\rdom\_dk_safe.png').convert('RGB'))
board = read_board(img)
tc = pc = 0
for r in board:
    n = r['cell']
    tok = r['type'] == TRUTH_T[n]
    pok = r['pip'] == TRUTH_P[n]
    tc += tok; pc += pok
    flag = '' if (tok and pok) else '  <-- ' + ('' if tok else 'TYPE ') + ('' if pok else 'PIP')
    print(f"  #{n:2d} {r['type']:9s} pip={r['pip']} (truth {TRUTH_T[n]},{TRUTH_P[n]}){flag}")
print(f"type {tc}/15   pip {pc}/15")
