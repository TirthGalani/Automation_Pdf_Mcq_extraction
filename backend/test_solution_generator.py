import sys
import os
from pathlib import Path
import pandas as pd

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.solution_generator import (
    render_matplotlib_diagram,
    generate_solutions_for_df,
    normalize_df_columns,
    export_df_to_styled_excel,
)

def test_matplotlib_rendering():
    print("\n--- Testing Matplotlib Diagram Execution ---")
    test_img = Path(__file__).resolve().parent / "extracted_images" / "test_diag.png"
    code = """
import numpy as np
import matplotlib.pyplot as plt

x = np.linspace(-3, 3, 200)
y = x**2 - 4

plt.plot(x, y, color='#1f77b4', lw=2, label=r'$f(x) = x^2 - 4$')
plt.axhline(0, color='black', lw=1, ls='--')
plt.axvline(0, color='black', lw=1, ls='--')
plt.scatter([-2, 2], [0, 0], color='red', zorder=5, label='Roots: $x = \\pm 2$')
plt.title(r'Graph of $f(x) = x^2 - 4$', fontsize=12, fontweight='bold')
plt.xlabel('x')
plt.ylabel('y')
plt.grid(True, linestyle=':', alpha=0.6)
plt.legend()
plt.tight_layout()
plt.savefig(OUTPUT_IMAGE_PATH, bbox_inches='tight', dpi=300, facecolor='white')
"""
    success = render_matplotlib_diagram(code, test_img)
    print(f"Diagram rendered: {success}, File exists: {test_img.exists()}, Size: {test_img.stat().st_size if test_img.exists() else 0} bytes")
    assert success and test_img.exists() and test_img.stat().st_size > 0
    print("[PASS] Matplotlib rendering test passed!")


def test_df_normalization_and_solving():
    print("\n--- Testing DataFrame Normalization & Solution Generation ---")
    sample_data = [
        {
            "ID": "1",
            "Question Text": "A particle moves with uniform acceleration $a = 2\\text{ m/s}^2$ starting from rest. Find its velocity after $t = 5\\text{ s}$.",
            "Option A": "$10\\text{ m/s}$",
            "Option B": "$20\\text{ m/s}$",
            "Option C": "$5\\text{ m/s}$",
            "Option D": "$25\\text{ m/s}$",
            "Subject": "Physics",
            "Chapter": "Kinematics",
        },
        {
            "ID": "2",
            "Question Text": "For the quadratic equation $x^2 - 4x + 3 = 0$, find the roots of the equation.",
            "Option A": "$x = 1, 3$",
            "Option B": "$x = -1, -3$",
            "Option C": "$x = 2, 4$",
            "Option D": "$x = 0, 4$",
            "Subject": "Mathematics",
            "Chapter": "Quadratic Equations",
        }
    ]

    df = pd.DataFrame(sample_data)
    print(f"Input DataFrame shape: {df.shape}")

    solved_df = generate_solutions_for_df(
        df=df,
        generate_images=True,
    )

    print("\nSolved DataFrame output:")
    for idx, r in solved_df.iterrows():
        print(f"\n[Q{r.get('ID')}] Answer: {r.get('Answer')}")
        print(f"Solution: {r.get('Solution')[:120]}...")
        print(f"Solution Image: {r.get('Solution Image')}")

    out_excel = Path(__file__).resolve().parent / "extracted_images" / "test_solved_output.xlsx"
    export_df_to_styled_excel(solved_df, out_excel)
    print(f"\nExported Solved Excel: {out_excel.exists()} ({out_excel.stat().st_size} bytes)")
    assert out_excel.exists() and out_excel.stat().st_size > 0
    print("[PASS] DataFrame solving & Excel export test passed successfully!")


if __name__ == "__main__":
    test_matplotlib_rendering()
    test_df_normalization_and_solving()
