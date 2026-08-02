# Discord Bot Integration for Config Checker

This guide explains how to integrate the Arizona Meshtastic Config Checker logic into a Discord bot, enabling a `/configcheck` slash command for your server.

## Overview

Since the config checker is a pure client-side web app, the Discord bot runs separately and reuses the same validation logic. The bot:

1. Accepts a config file attachment via the `/configcheck` slash command
2. Parses it using the same logic as the web app
3. Returns a formatted embed with the check results

## Architecture

```
Discord User
    |
    | /configcheck [attachment] [region] [node_type]
    v
Discord Bot (Node.js)
    |
    | Parse config file (reuses parser.js + checker.js logic)
    v
Formatted Embed Response
```

## Setup

### Prerequisites

- Node.js 18+
- A Discord bot token (create one at [discord.com/developers](https://discord.com/developers/applications))
- Bot invited to your server with `applications.commands` scope

### Installation

```bash
npm init -y
npm install discord.js js-yaml protobufjs
```

### Bot Code

Create `bot.js`:

```javascript
const { Client, GatewayIntentBits, SlashCommandBuilder, REST, Routes, EmbedBuilder, AttachmentBuilder } = require('discord.js');
const fs = require('fs');
const path = require('path');
const jsyaml = require('js-yaml');

// Copy checker.js and parser.js logic into Node.js-compatible modules,
// or use the reference implementation below.

const TOKEN = process.env.DISCORD_BOT_TOKEN;
const CLIENT_ID = process.env.DISCORD_CLIENT_ID;

const client = new Client({ intents: [GatewayIntentBits.Guilds] });

// Register slash command
const commands = [
  new SlashCommandBuilder()
    .setName('configcheck')
    .setDescription('Check your Meshtastic config against AZ community recommendations')
    .addAttachmentOption(opt =>
      opt.setName('config')
        .setDescription('Your Meshtastic config file (.cfg, .yaml, .yml, .json)')
        .setRequired(true))
    .addStringOption(opt =>
      opt.setName('region')
        .setDescription('Your region')
        .setRequired(false)
        .addChoices(
          { name: 'Metro (Phoenix/Tucson)', value: 'metro' },
          { name: 'Rural Arizona', value: 'rural' }
        ))
    .addStringOption(opt =>
      opt.setName('node_type')
        .setDescription('Node type')
        .setRequired(false)
        .addChoices(
          { name: 'Stationary', value: 'stationary' },
          { name: 'Mobile', value: 'mobile' }
        ))
].map(cmd => cmd.toJSON());

async function registerCommands() {
  const rest = new REST().setToken(TOKEN);
  await rest.put(Routes.applicationCommands(CLIENT_ID), { body: commands });
  console.log('Slash commands registered.');
}

client.on('interactionCreate', async interaction => {
  if (!interaction.isChatInputCommand()) return;
  if (interaction.commandName !== 'configcheck') return;

  await interaction.deferReply();

  try {
    const attachment = interaction.options.getAttachment('config');
    const region = interaction.options.getString('region') || 'metro';
    const nodeType = interaction.options.getString('node_type') || 'stationary';

    // Download the attachment
    const response = await fetch(attachment.url);
    const buffer = await response.arrayBuffer();

    // Parse and check (reuse your parser/checker logic here)
    // const config = await ConfigParser.parse(buffer, attachment.name);
    // const report = ConfigChecker.check(config, region, nodeType);

    // For this example, we'll show the embed structure:
    const embed = new EmbedBuilder()
      .setTitle('Meshtastic Config Check')
      .setColor(0xE8602C)
      .setDescription(`Checked **${attachment.name}** for ${region} / ${nodeType}`)
      .setFooter({ text: 'Arizona Meshtastic Community - config.azmsh.net' });

    // Add fields for each category:
    // report.categories.forEach(cat => {
    //   const summary = cat.checks.map(c => {
    //     const icon = { pass: '✅', fail: '❌', warn: '⚠️', info: 'ℹ️' }[c.status];
    //     return `${icon} ${c.title}`;
    //   }).join('\n');
    //   embed.addFields({ name: `${cat.icon} ${cat.title}`, value: summary });
    // });

    await interaction.editReply({ embeds: [embed] });
  } catch (err) {
    await interaction.editReply(`Error checking config: ${err.message}`);
  }
});

client.once('ready', () => {
  console.log(`Bot ready as ${client.user.tag}`);
  registerCommands();
});

client.login(TOKEN);
```

### Running

```bash
DISCORD_BOT_TOKEN=your_token DISCORD_CLIENT_ID=your_client_id node bot.js
```

## Reusing Checker Logic

The core validation logic lives in two files:

- `js/parser.js` — Parses .cfg (protobuf), .yaml, and .json config files
- `js/checker.js` — Validates parsed config against AZ recommendations

To use them in Node.js:

1. Copy the `ConfigParser` and `ConfigChecker` objects
2. Replace browser globals (`window.MeshtasticProto`) with `require()` calls
3. Replace `jsyaml` CDN with `require('js-yaml')`
4. Replace `protobuf` CDN with `require('protobufjs')`

The recommendation constants in `checker.js` are the source of truth. When they change on the web app, update the bot's copy.

## Slash Command Reference

```
/configcheck config:<file> [region:metro|rural] [node_type:stationary|mobile]
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| config | Yes | - | Config file attachment |
| region | No | metro | Metro or rural AZ |
| node_type | No | stationary | Stationary or mobile node |

## Response Format

The bot responds with a Discord embed containing:

- Health score (0-100)
- Category-by-category results with pass/fail/warn icons
- Failed checks include the current value, expected value, and how to fix
- Link to the web app for full details

## Privacy

The bot processes config files in memory only. No data is stored or logged. Config files may contain encryption keys and should be handled carefully.

## Community

- Web app: [config.azmsh.net](https://config.azmsh.net)
- AZ Meshtastic: [azmsh.net](https://azmsh.net)
- Discord: Arizona Meshtastic community server
