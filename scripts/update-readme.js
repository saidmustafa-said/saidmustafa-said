const fs = require('fs');

// Read events.json file to get recent GitHub activities
const events = JSON.parse(fs.readFileSync('events.json', 'utf8'));

// Create a set to store unique repo names and an array for the list of repos
const repoSet = new Set();
let repoList = [];

// Loop through each event to filter "PushEvent" and "PullRequestEvent"
events.forEach(event => {
  if ((event.type === "PushEvent" || event.type === "PullRequestEvent") && repoSet.size < 3) {
    const repoName = event.repo.name;
    if (!repoSet.has(repoName)) {
      repoSet.add(repoName);
      repoList.push(`- [${repoName}](https://github.com/${repoName})`);
    }
  }
});

// Prepare the section for recent repositories
let newRepoSection = `# 📂 Recent Repositories Worked On:\n\n`;
newRepoSection += repoList.join('\n') + '\n';

// Read the current README.md content
let readmeContent = fs.readFileSync('README.md', 'utf8');

// Replace the existing "Recent Repositories Worked On" section with the updated one
const updatedReadme = readmeContent.replace(
  /# 📂 Recent Repositories Worked On:[\s\S]*?(?=\n#|$)/,
  newRepoSection
);

// Write the updated README content back to README.md
fs.writeFileSync('README.md', updatedReadme);

console.log('README.md updated successfully with recent repositories.');
