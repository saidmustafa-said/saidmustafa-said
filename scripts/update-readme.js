const fs = require('fs');
const axios = require('axios');

// GitHub API Endpoints
const GITHUB_USERNAME = 'saidmustafa-said';
const REPO_URL = `https://api.github.com/users/${GITHUB_USERNAME}/repos?sort=updated&per_page=3`;
const EVENTS_URL = `https://api.github.com/users/${GITHUB_USERNAME}/events?per_page=5`;

// Fetch recent repositories
async function fetchRecentRepos() {
    try {
        const response = await axios.get(REPO_URL);
        return response.data.map(repo => `- [${repo.name}](${repo.html_url}) - ${repo.description || "No description"}`).join('\n');
    } catch (error) {
        console.error('Error fetching repos:', error);
    }
}

// Fetch recent activities
async function fetchRecentActivity() {
    try {
        const response = await axios.get(EVENTS_URL);
        return response.data
            .filter(event => event.type === 'PushEvent' || event.type === 'PullRequestEvent')
            .slice(0, 5)
            .map(event => {
                const repoName = event.repo.name;
                const repoUrl = `https://github.com/${repoName}`;
                if (event.type === 'PushEvent') {
                    return `- Pushed code to [${repoName}](${repoUrl}) on \`${event.payload.ref.replace('refs/heads/', '')}\``;
                } else if (event.type === 'PullRequestEvent') {
                    return `- Merged a pull request in [${repoName}](${repoUrl})`;
                }
            })
            .join('\n');
    } catch (error) {
        console.error('Error fetching activities:', error);
    }
}

// Update the README file
async function updateReadme() {
    const readmeContent = fs.readFileSync('README.md', 'utf-8');

    // Fetch recent data
    const recentRepos = await fetchRecentRepos();
    const recentActivities = await fetchRecentActivity();

    // Replace placeholders in the README
    const newReadme = readmeContent
        .replace(/<!-- RECENT_REPOS_START -->[\s\S]*<!-- RECENT_REPOS_END -->/, `<!-- RECENT_REPOS_START -->\n${recentRepos}\n<!-- RECENT_REPOS_END -->`)
        .replace(/<!-- RECENT_ACTIVITY_START -->[\s\S]*<!-- RECENT_ACTIVITY_END -->/, `<!-- RECENT_ACTIVITY_START -->\n${recentActivities}\n<!-- RECENT_ACTIVITY_END -->`);

    // Write the updated content to the README file
    fs.writeFileSync('README.md', newReadme);
}

updateReadme();
