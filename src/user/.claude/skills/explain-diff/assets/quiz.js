/* explain-pr quiz interaction — inline this verbatim inside a <script> tag.
 * Markup contract (see assets/palette.md):
 *   <div class="q">
 *     <div class="stem">Question text?</div>
 *     <button class="opt" data-correct="false" data-fb="why this is wrong">Option A</button>
 *     <button class="opt" data-correct="true"  data-fb="why this is right">Option B</button>
 *     <div class="feedback"></div>
 *   </div>
 * On click: locks the question, marks correct/incorrect, reveals the clicked
 * option's feedback (plus points at the right answer if they missed).
 */
document.addEventListener("click", function (e) {
  var opt = e.target.closest(".opt");
  if (!opt) return;
  var q = opt.closest(".q");
  if (!q || q.dataset.done) return;
  q.dataset.done = "1";

  var chosenRight = opt.dataset.correct === "true";
  opt.classList.add(chosenRight ? "correct" : "incorrect");

  q.querySelectorAll(".opt").forEach(function (o) {
    o.disabled = true;
    if (!chosenRight && o.dataset.correct === "true") o.classList.add("correct");
  });

  var fb = q.querySelector(".feedback");
  if (fb) {
    var right = q.querySelector('.opt[data-correct="true"]');
    fb.textContent =
      (chosenRight ? "Correct. " : "Not quite. ") +
      (opt.dataset.fb || "") +
      (!chosenRight && right && right.dataset.fb ? "  —  " + right.dataset.fb : "");
    fb.classList.add("show");
  }
});
