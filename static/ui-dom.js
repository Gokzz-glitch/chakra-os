function uiNode(tag, value, className) {
  const node = document.createElement(tag);
  if (value != null) node.textContent = String(value);
  if (className) node.className = className;
  return node;
}
function uiButton(label, action) {
  const button = uiNode('button', label, 'btn ghost');
  button.type = 'button';
  button.addEventListener('click', action);
  return button;
}
function uiOption(value, label) {
  const option = uiNode('option', label);
  option.value = value;
  return option;
}
function clipOptions(videos) {
  return videos.map(video => {
    const option = uiOption(video.name, video.name + ' (' + (video.size_bytes / 1024).toFixed(0) + ' KB)');
    option.dataset.url = video.stream_url;
    option.dataset.fmt = video.format;
    return option;
  });
}
