fetch('https://html.duckduckgo.com/html/?q=vercel+fastapi+%22Could+not+find+a+top-level+app%22')
  .then(res => res.text())
  .then(text => {
    const matches = text.match(/class="result__snippet[^>]*>(.*?)<\/a>/g);
    console.log(matches || "No matches.");
  });