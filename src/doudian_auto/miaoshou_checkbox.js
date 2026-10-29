(value, checked, marker) => {
  const xs = [...document.querySelectorAll('input[type=checkbox]')]
    .filter(x => x.offsetParent !== null && x.value === value && !x.disabled);
  if (xs.length !== 1) return {count: xs.length};
  const input = xs[0];
  if (input.checked === checked) return {count: 1, unchanged: true};
  const label = input.closest('label');
  const target = input.parentElement?.querySelector('.el-checkbox__inner');
  // A method label also wraps disabled textareas and image controls. Its center
  // can hit one of those instead of the checkbox. Mark the observed small box.
  if (!label || !target || target.closest('label') !== label) return {count: 0};
  const rect = target.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return {count: 0};
  target.setAttribute('data-codex-miao-batch', marker);
  return {count: 1};
}
