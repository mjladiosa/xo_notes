import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
from typing import Dict, Set, Tuple, Union, List
import json
import os
import re
import datetime
import asyncio

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

class NoteEditModal(Modal):
    def __init__(self, title, original_content, view):
        super().__init__(title=f"Edit Note: {title}")
        self.title = title
        self.view = view
        
        self.content_input = TextInput(
            label="Note Content",
            style=discord.TextStyle.paragraph,
            default=original_content,
            required=True
        )
        self.add_item(self.content_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        new_content = self.content_input.value
        self.view.note_content = new_content
        
        note_system = bot.get_cog("NoteSystem")
        if note_system:
            old_content = note_system.notes[self.title]["content"]
            note_system.notes[self.title]["content"] = new_content
            note_system.notes[self.title]["last_edited"] = {
                "user": interaction.user.name,
                "user_id": interaction.user.id,
                "timestamp": datetime.datetime.now().isoformat()
            }
            note_system.save_notes()
            
            await note_system.notify_subscribers(self.title, interaction.user, old_content, new_content)
        
        if self.view.is_expanded:
            display_content = new_content
        else:
            display_content = f"📝 **{self.title}** (click to view)"
        
        await interaction.response.edit_message(content=display_content, view=self.view)

class NoteView(View):
    def __init__(self, title, note_content, subscribers=None):
        super().__init__(timeout=None)
        self.note_content = note_content
        self.title = title
        self.is_expanded = False
        self.subscribers = subscribers or []
        
        self.toggle_button = Button(
            label="♪・Show Note",
            style=discord.ButtonStyle.primary,
            custom_id="toggle_note"
        )
        self.toggle_button.callback = self.toggle_callback
        self.add_item(self.toggle_button)
        
        self.edit_button = Button(
            label="✏️ Edit",
            style=discord.ButtonStyle.secondary,
            custom_id="edit_note"
        )
        self.edit_button.callback = self.edit_callback
        self.add_item(self.edit_button)

        self.subscribe_button = Button(
            label="🔔 Subscribe",
            style=discord.ButtonStyle.success,
            custom_id="subscribe_note"
        )
        self.subscribe_button.callback = self.subscribe_callback
        self.add_item(self.subscribe_button)

    async def toggle_callback(self, interaction: discord.Interaction):
        self.is_expanded = not self.is_expanded
        
        if self.is_expanded:
            self.toggle_button.label = "♪・Hide Note ・♪"
            content = self.note_content
        else:
            self.toggle_button.label = "♪・ Show Note ・♪"
            content = f"📝 **{self.title}** (click to view)"

        await interaction.response.edit_message(content=content, view=self)
    
    async def edit_callback(self, interaction: discord.Interaction):
        modal = NoteEditModal(self.title, self.note_content, self)
        await interaction.response.send_modal(modal)
    
    async def subscribe_callback(self, interaction: discord.Interaction):
        note_system = bot.get_cog("NoteSystem")
        user_id = str(interaction.user.id)
        
        if not note_system:
            await interaction.response.send_message("Note system is not available.", ephemeral=True)
            return
            
        if self.title not in note_system.notes:
            await interaction.response.send_message(f"Note '{self.title}' no longer exists.", ephemeral=True)
            return
            
        if "subscribers" not in note_system.notes[self.title]:
            note_system.notes[self.title]["subscribers"] = []
            
        if user_id in note_system.notes[self.title]["subscribers"]:
            note_system.notes[self.title]["subscribers"].remove(user_id)
            self.subscribe_button.label = "🔔 Subscribe"
            self.subscribe_button.style = discord.ButtonStyle.success
            message = f"You've unsubscribed from the note '{self.title}'."
        else:
            note_system.notes[self.title]["subscribers"].append(user_id)
            self.subscribe_button.label = "🔕 Unsubscribe"
            self.subscribe_button.style = discord.ButtonStyle.danger
            message = f"You've subscribed to the note '{self.title}'. You'll be notified when it's updated."
            
        note_system.save_notes()
        await interaction.response.send_message(message, ephemeral=True)
        
        self.subscribers = note_system.notes[self.title]["subscribers"]

class ChecklistEditModal(Modal):
    def __init__(self, title, original_items, view):
        super().__init__(title=f"Edit Checklist: {title}")
        self.title = title
        self.view = view
        
        items_text = ", ".join(original_items)
        
        self.items_input = TextInput(
            label="Items (comma separated)",
            style=discord.TextStyle.paragraph,
            default=items_text,
            required=True
        )
        self.add_item(self.items_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        new_items = [item.strip() for item in self.items_input.value.split(',')]
        
        checklist_system = bot.get_cog("NoteSystem")
        if checklist_system:
            checklist_system.checklists[self.title] = new_items
            checklist_system.save_checklists()
        
        new_view = ChecklistView(self.title, new_items)
        
        embed = discord.Embed(
            title=self.title,
            color=discord.Color.blue()
        )
        
        await interaction.response.edit_message(embed=embed, view=new_view)

class ChecklistView(View):
    def __init__(self, title, items):
        super().__init__(timeout=None)
        self.items = items
        self.title = title
        self.checked_items = [False] * len(items)
        
        self.update_buttons()
        
        self.edit_button = Button(
            label="✏️ Edit",
            style=discord.ButtonStyle.secondary,
            custom_id="edit_checklist"
        )
        self.edit_button.callback = self.edit_callback
        self.add_item(self.edit_button)
    
    def update_buttons(self):
        for child in list(self.children):
            if child.custom_id and child.custom_id.startswith("check_"):
                self.remove_item(child)
        
        for i, item in enumerate(self.items):
            prefix = "☑" if self.checked_items[i] else "☐"
            style = discord.ButtonStyle.success if self.checked_items[i] else discord.ButtonStyle.secondary
            
            button = Button(
                label=f"{prefix} {item}",
                custom_id=f"check_{i}",
                style=style
            )
            button.callback = self.create_check_callback(i)
            self.add_item(button)

    def create_check_callback(self, index):
        async def check_callback(interaction: discord.Interaction):
            self.checked_items[index] = not self.checked_items[index]
            self.update_buttons()
            await interaction.response.edit_message(view=self)
        return check_callback
    
    async def edit_callback(self, interaction: discord.Interaction):
        modal = ChecklistEditModal(self.title, self.items, self)
        await interaction.response.send_modal(modal)

class NoteSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.notes = {}
        self.checklists = {}
        self.active_threads = {}
        self.conversation_buffer = {}
        self.load_notes()
        self.load_checklists()

    def save_notes(self):
        """Save notes to a JSON file"""
        with open('xo_notes.json', 'w') as f:
            json.dump(self.notes, f)

    def load_notes(self):
        """Load notes from JSON file"""
        try:
            if os.path.exists('xo_notes.json'):
                with open('xo_notes.json', 'r') as f:
                    self.notes = json.load(f)
        except Exception as e:
            print(f"Error loading notes: {e}")
            self.notes = {}
    
    def save_checklists(self):
        """Save checklists to a JSON file"""
        with open('xo_checklists.json', 'w') as f:
            json.dump(self.checklists, f)

    def load_checklists(self):
        """Load checklists from JSON file"""
        try:
            if os.path.exists('xo_checklists.json'):
                with open('xo_checklists.json', 'r') as f:
                    self.checklists = json.load(f)
        except Exception as e:
            print(f"Error loading checklists: {e}")
            self.checklists = {}

    async def notify_subscribers(self, note_title, editor, old_content, new_content):
        """Send notifications to all subscribers of a note when it's edited"""
        if note_title not in self.notes:
            return
            
        subscribers = self.notes[note_title].get("subscribers", [])
        if not subscribers:
            return
        
        notification_channel_id = YOUR_CHANNEL_ID
        notification_channel = self.bot.get_channel(notification_channel_id)
        
        if not notification_channel:
            print(f"Could not find notification channel with ID {notification_channel_id}")
            return
            
        embed = discord.Embed(
            title=f"📝 Note Update: {note_title}",
            description=f"The note '{note_title}' has been updated by {editor.name}",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now()
        )
        
        mentions = []
        for user_id in subscribers:
            mentions.append(f"<@{user_id}>")
        
        if len(mentions) > 5:
            subscriber_text = ", ".join(mentions[:5]) + f" and {len(mentions) - 5} others"
        else:
            subscriber_text = ", ".join(mentions)
        
        if len(old_content) > 500 or len(new_content) > 500:
            embed.add_field(
                name="Changes",
                value="The note was extensively modified.",
                inline=False
            )
        else:
            old_len = len(old_content)
            new_len = len(new_content)
            diff = new_len - old_len
            
            if diff > 0:
                embed.add_field(
                    name="Changes",
                    value=f"Added approximately {diff} characters to the note.",
                    inline=False
                )
            elif diff < 0:
                embed.add_field(
                    name="Changes",
                    value=f"Removed approximately {abs(diff)} characters from the note.",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Changes",
                    value="The note was modified but has the same length.",
                    inline=False
                )
        
        view = discord.ui.View(timeout=None)
        button = discord.ui.Button(
            label="View Note",
            style=discord.ButtonStyle.primary,
            custom_id=f"view_note_{note_title}"
        )
        
        async def view_callback(interaction):
            note_content = self.notes[note_title]["content"]
            note_view = NoteView(note_title, note_content, subscribers)
            
            if str(interaction.user.id) in subscribers:
                note_view.subscribe_button.label = "🔕 Unsubscribe"
                note_view.subscribe_button.style = discord.ButtonStyle.danger
            
            await interaction.response.send_message(f"📝 **{note_title}** (click to view)", view=note_view)
        
        button.callback = view_callback
        view.add_item(button)
        
        if subscriber_text:
            notification_text = f"🔔 Note update notification for {subscriber_text}"
        else:
            notification_text = "🔔 Note update notification"
            
        await notification_channel.send(notification_text, embed=embed, view=view)

    @commands.command(name='note')
    async def create_note(self, ctx, title: str, *, content: str):
        """Create a new note with a dropdown"""
        self.notes[title] = {
            "content": content,
            "created_by": {
                "user": ctx.author.name,
                "user_id": ctx.author.id,
                "timestamp": datetime.datetime.now().isoformat()
            },
            "subscribers": [str(ctx.author.id)]
        }
        self.save_notes()
        
        view = NoteView(title, content, [str(ctx.author.id)])
        view.subscribe_button.label = "🔕 Unsubscribe"
        view.subscribe_button.style = discord.ButtonStyle.danger
        
        await ctx.send(f"📝 **{title}** (click to view)", view=view)

    @commands.command(name='checklist')
    async def create_checklist(self, ctx, title: str, *, items: str):
        """Create a checklist with toggleable items
        ・ Usage: !checklist "My List" item1, item2, item3"""
        item_list = [item.strip() for item in items.split(',')]
        
        self.checklists[title] = item_list
        self.save_checklists()
        
        embed = discord.Embed(
            title=title,
            color=discord.Color.blue()
        )
        
        view = ChecklistView(title, item_list)
        await ctx.send(embed=embed, view=view)

    @commands.command(name='thread_note')
    async def create_thread_note(self, ctx, thread: discord.Thread = None):
        """Create a note from a thread's messages
        ・ Usage: !thread_note [thread mention or ID]
        If no thread is provided, uses the current thread"""
        
        if thread is None:
            if isinstance(ctx.channel, discord.Thread):
                thread = ctx.channel
            else:
                await ctx.send("Please provide a thread mention or ID, or use this command within a thread.")
                return
        
        await ctx.send(f"Creating note from thread {thread.name}... This may take a moment.")
        
        try:
            messages = []
            async for message in thread.history(limit=300, oldest_first=True):
                if not message.author.bot:
                    messages.append(message)
            
            if not messages:
                await ctx.send("No messages found in this thread.")
                return
                
            note_content = f"# Thread Note: {thread.name}\n"
            note_content += f"Created: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            note_content += f"Thread started by: {thread.owner.name if thread.owner else 'Unknown'}\n\n"
            
            for i, msg in enumerate(messages):
                timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M")
                note_content += f"**{msg.author.name}** ({timestamp}):\n{msg.content}\n\n"
                
                if msg.attachments:
                    note_content += "**Attachments:**\n"
                    for attachment in msg.attachments:
                        note_content += f"- {attachment.url}\n"
                    note_content += "\n"
                    
            title = f"Thread: {thread.name}"
            self.notes[title] = {
                "content": note_content,
                "created_by": {
                    "user": ctx.author.name,
                    "user_id": ctx.author.id,
                    "timestamp": datetime.datetime.now().isoformat()
                },
                "thread_id": thread.id,
                "subscribers": [str(ctx.author.id)]
            }
            self.save_notes()
            
            view = NoteView(title, note_content, [str(ctx.author.id)])
            view.subscribe_button.label = "🔕 Unsubscribe"
            view.subscribe_button.style = discord.ButtonStyle.danger
            
            await ctx.send(f"📝 Thread note created: **{title}** (click to view)", view=view)
            
        except Exception as e:
            await ctx.send(f"Error creating thread note: {str(e)}")

    @commands.command(name='auto_note')
    async def toggle_auto_note(self, ctx, thread: discord.Thread = None):
        """Toggle automatic note creation for a thread
        ・ Usage: !auto_note [thread mention or ID]
        If no thread is provided, uses the current thread"""
        
        if thread is None:
            if isinstance(ctx.channel, discord.Thread):
                thread = ctx.channel
            else:
                await ctx.send("Please provide a thread mention or ID, or use this command within a thread.")
                return
                
        thread_id = str(thread.id)
        
        if thread_id in self.active_threads:

            del self.active_threads[thread_id]
            await ctx.send(f"Automatic note creation disabled for thread '{thread.name}'.")
        else:
            self.active_threads[thread_id] = {
                "name": thread.name,
                "creator": ctx.author.id,
                "subscribers": [str(ctx.author.id)],
                "last_update": datetime.datetime.now().isoformat()
            }
            await ctx.send(f"Automatic note creation enabled for thread '{thread.name}'. A note will be created when the thread is archived or manually with !thread_note.")

    @commands.command(name='conversation_note')
    async def toggle_conversation_note(self, ctx, duration: int = 10):
        """Start tracking conversation to create a note
        ・ Usage: !conversation_note [minutes=10]
        Records messages in this channel for the specified duration"""
        
        channel_id = str(ctx.channel.id)
        
        if channel_id in self.conversation_buffer:
            await ctx.send("Conversation tracking stopped. Creating note...")
            
            messages = self.conversation_buffer[channel_id]["messages"]
            del self.conversation_buffer[channel_id]
            
            if not messages:
                await ctx.send("No messages were captured.")
                return
                
            note_title = f"Conversation in {ctx.channel.name} ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M')})"
            note_content = f"# Conversation Note\n"
            note_content += f"Channel: {ctx.channel.name}\n"
            note_content += f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            note_content += f"Duration: {len(messages)} messages\n\n"
            
            for msg in messages:
                timestamp = msg.created_at.strftime("%H:%M:%S")
                note_content += f"**{msg.author.name}** ({timestamp}):\n{msg.content}\n\n"
                
                if msg.attachments:
                    note_content += "**Attachments:**\n"
                    for attachment in msg.attachments:
                        note_content += f"- {attachment.url}\n"
                    note_content += "\n"
          
            self.notes[note_title] = {
                "content": note_content,
                "created_by": {
                    "user": ctx.author.name,
                    "user_id": ctx.author.id,
                    "timestamp": datetime.datetime.now().isoformat()
                },
                "channel_id": ctx.channel.id,
                "subscribers": [str(ctx.author.id)]
            }
            self.save_notes()
            
            view = NoteView(note_title, note_content, [str(ctx.author.id)])
            view.subscribe_button.label = "🔕 Unsubscribe"
            view.subscribe_button.style = discord.ButtonStyle.danger
            
            await ctx.send(f"📝 Conversation note created: **{note_title}** (click to view)", view=view)
        else:
            self.conversation_buffer[channel_id] = {
                "start_time": datetime.datetime.now(),
                "end_time": datetime.datetime.now() + datetime.timedelta(minutes=duration),
                "creator": ctx.author.id,
                "messages": []
            }
            
            await ctx.send(f"🎙️ Now recording conversation in this channel for {duration} minutes. Use !conversation_note again to stop recording early.")
            
            self.bot.loop.create_task(self.auto_stop_conversation(ctx.channel, duration))

    async def auto_stop_conversation(self, channel, duration):
        """Automatically stop conversation tracking after the specified duration"""
        await asyncio.sleep(duration * 60)  # Convert minutes to seconds
        
        channel_id = str(channel.id)
        if channel_id in self.conversation_buffer:
            # Still tracking - create note
            messages = self.conversation_buffer[channel_id]["messages"]
            creator_id = self.conversation_buffer[channel_id]["creator"]
            del self.conversation_buffer[channel_id]
            
            if not messages:
                await channel.send("Conversation tracking ended. No messages were captured.")
                return
                
            note_title = f"Conversation in {channel.name} ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M')})"
            note_content = f"# Conversation Note\n"
            note_content += f"Channel: {channel.name}\n"
            note_content += f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            note_content += f"Duration: {duration} minutes ({len(messages)} messages)\n\n"
            
            for msg in messages:
                timestamp = msg.created_at.strftime("%H:%M:%S")
                note_content += f"**{msg.author.name}** ({timestamp}):\n{msg.content}\n\n"
                
                if msg.attachments:
                    note_content += "**Attachments:**\n"
                    for attachment in msg.attachments:
                        note_content += f"- {attachment.url}\n"
                    note_content += "\n"
            
            creator = await self.bot.fetch_user(creator_id)
            creator_name = creator.name if creator else "Unknown"
            
            self.notes[note_title] = {
                "content": note_content,
                "created_by": {
                    "user": creator_name,
                    "user_id": creator_id,
                    "timestamp": datetime.datetime.now().isoformat()
                },
                "channel_id": channel.id,
                "subscribers": [str(creator_id)]
            }
            self.save_notes()
            
            view = NoteView(note_title, note_content, [str(creator_id)])
            view.subscribe_button.label = "🔕 Unsubscribe"
            view.subscribe_button.style = discord.ButtonStyle.danger
            
            await channel.send(f"📝 Conversation recording ended. Note created: **{note_title}** (click to view)", view=view)

    @commands.command(name='list_notes')
    async def list_notes(self, ctx):
        """♪・List all saved notes・♪"""
        if not self.notes:
            await ctx.send("▪ No notes saved.")
            return
            
        embed = discord.Embed(
            title="♪ ・ Saved Notes ・ ♪",
            color=discord.Color.blue()
        )
        
        sorted_notes = sorted(
            self.notes.items(),
            key=lambda x: x[1].get("created_by", {}).get("timestamp", ""), 
            reverse=True
        )
        
        for title, data in sorted_notes:
            creator = data.get("created_by", {}).get("user", "Unknown")
            timestamp = data.get("created_by", {}).get("timestamp", "")
            
            if timestamp:
                try:
                    dt = datetime.datetime.fromisoformat(timestamp)
                    timestamp = dt.strftime("%Y-%m-%d")
                except:
                    pass
                    
            subscribers = len(data.get("subscribers", []))
            value = f"Created by: {creator}"
            if timestamp:
                value += f" on {timestamp}"
            if subscribers > 0:
                value += f" | {subscribers} subscribers"
                
            embed.add_field(name=title, value=value, inline=False)
            
        await ctx.send(embed=embed)

    @commands.command(name='list_checklists')
    async def list_checklists(self, ctx):
        """♪・List all saved checklists・♪"""
        if not self.checklists:
            await ctx.send("▪ No checklists saved.")
            return
            
        embed = discord.Embed(
            title="♪ ・ Saved Checklists ・ ♪",
            color=discord.Color.blue()
        )
        
        for title in self.checklists.keys():
            item_count = len(self.checklists[title])
            embed.add_field(name=title, value=f"{item_count} items", inline=False)
            
        await ctx.send(embed=embed)
   
    @commands.command(name='show_note')
    async def show_note(self, ctx, *, title: str):
        """♪・Display a specific note by title・♪"""
        if title in self.notes:
            content = self.notes[title]["content"]
            subscribers = self.notes[title].get("subscribers", [])
            
            view = NoteView(title, content, subscribers)

            if str(ctx.author.id) in subscribers:
                view.subscribe_button.label = "🔕 Unsubscribe"
                view.subscribe_button.style = discord.ButtonStyle.danger
                
            await ctx.send(f"📝 **{title}** (click to view)", view=view)
        else:
            await ctx.send(f"▪ Note '{title}' not found. Use `!list_notes` to see available notes.")
    
    @commands.command(name='show_checklist')
    async def show_checklist(self, ctx, *, title: str):
        """♪・Display a specific checklist by title・♪"""
        if title in self.checklists:
            item_list = self.checklists[title]
            embed = discord.Embed(
                title=title,
                color=discord.Color.blue()
            )
            view = ChecklistView(title, item_list)
            await ctx.send(embed=embed, view=view)
        else:
            await ctx.send(f"▪ Checklist '{title}' not found. Use `!list_checklists` to see available checklists.")
        
    @commands.command(name='delete_note')
    async def delete_note(self, ctx, title: str):
        """♪・Delete a saved note・♪"""
        if title in self.notes:
            del self.notes[title]
            self.save_notes()
            await ctx.send(f"▪ Note '{title}' deleted.・♪")
        else:
            await ctx.send(f"▪ Note '{title}' not found.・♪")
    
    @commands.command(name='delete_checklist')
    async def delete_checklist(self, ctx, title: str):
        """♪・Delete a saved checklist・♪"""
        if title in self.checklists:
            del self.checklists[title]
            self.save_checklists()
            await ctx.send(f"▪ Checklist '{title}' deleted.・♪")
        else:
            await ctx.send(f"▪ Checklist '{title}' not found.・♪")
    
    @commands.command(name='subscribe')
    async def subscribe_to_note(self, ctx, *, title: str):
        """Subscribe to updates for a specific note"""
        if title not in self.notes:
            await ctx.send(f"▪ Note '{title}' not found. Use `!list_notes` to see available notes.")
            return
            
        if "subscribers" not in self.notes[title]:
            self.notes[title]["subscribers"] = []
            
        user_id = str(ctx.author.id)
        
        if user_id in self.notes[title]["subscribers"]:
            await ctx.send(f"You're already subscribed to '{title}'.")
        else:
            self.notes[title]["subscribers"].append(user_id)
            self.save_notes()
            await ctx.send(f"You've subscribed to '{title}'. You'll be notified when it's updated.")
    
    @commands.command(name='unsubscribe')
    async def unsubscribe_from_note(self, ctx, *, title: str):
        """Unsubscribe from updates for a specific note"""
        if title not in self.notes:
            await ctx.send(f"▪ Note '{title}' not found. Use `!list_notes` to see available notes.")
            return
            
        if "subscribers" not in self.notes[title]:
            self.notes[title]["subscribers"] = []
            
        user_id = str(ctx.author.id)
        
        if user_id in self.notes[title]["subscribers"]:
            self.notes[title]["subscribers"].remove(user_id)
            self.save_notes()
            await ctx.send(f"You've unsubscribed from '{title}'.")
        else:
            await ctx.send(f"You're not subscribed to '{title}'.")
    
    @commands.command(name='my_subscriptions')
    async def list_subscriptions(self, ctx):
        """List all notes you're subscribed to"""
        user_id = str(ctx.author.id)
        subscribed_notes = []
        
        for title, data in self.notes.items():
            if "subscribers" in data and user_id in data["subscribers"]:
                subscribed_notes.append(title)
                
        if not subscribed_notes:
            await ctx.send("You're not subscribed to any notes.")
            return
            
        embed = discord.Embed(
            title="🔔 Your Note Subscriptions",
            color=discord.Color.blue()
        )
        
        for title in subscribed_notes:
            embed.add_field(name=title, value="Use `!show_note \"" + title + "\"` to view", inline=False)
            
        await ctx.send(embed=embed)
    
    @commands.Cog.listener()
    async def on_message(self, message):
        # Skip bot messages
        if message.author.bot:
            return
            
        channel_id = str(message.channel.id)
        if channel_id in self.conversation_buffer:
            # Add message to buffer
            self.conversation_buffer[channel_id]["messages"].append(message)

class ChannelManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.linked_channels = {}
        self.load_links()

    def save_links(self):
        """♪・Save channel links to a JSON file・♪"""
        links_dict = {
            f"{server_id},{channel_id}": [
                f"{linked_server},{linked_channel}"
                for linked_server, linked_channel in linked_channels
            ]
            for (server_id, channel_id), linked_channels in self.linked_channels.items()
        }
        
        with open('xo_channel_links.json', 'w') as f:
            json.dump(links_dict, f)

    def load_links(self):
        """Load channel links from JSON file"""
        try:
            if os.path.exists('xo_channel_links.json'):
                with open('xo_channel_links.json', 'r') as f:
                    links_dict = json.load(f)
                
                self.linked_channels = {
                    tuple(map(int, key.split(','))): {
                        tuple(map(int, chan.split(','))) for chan in channels
                    }
                    for key, channels in links_dict.items()
                }
        except Exception as e:
            print(f"▪ Error loading channel links: {e}")
            self.linked_channels = {}

    @commands.command(name='xo')
    async def help_command(self, ctx):
        """♪・Shows all available commands and their descriptions"""
        embed = discord.Embed(
            title="・𝐗𝐨 𝐁𝐨𝐭 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬・",
            description="♪・Here are all the commands you can use・♪",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="♪・Message♻️Clear・♪",
            value="・``!delete <number>`` - Deletes specified number of messages\n・・Example: `!delete 10`",
            inline=False
        )
        
        embed.add_field(
            name="♪・Channel🔗Linking ・♪",
            value=(
                "・``!link <channel1> <channel2>`` - Links two channels/threads\n"
                "     ・ Use channel/thread IDs to link, like: `!link 1234567890 9876543210`\n"
                "・``!unlink <channel1> <channel2>`` - Removes link between channels/threads\n"
                "・``!links`` - Shows all linked channels/threads in current server"
            ),
            inline=False
        )

        embed.add_field(
            name="♪・ Note Commands ・♪",
            value=(
                "・``!note ʹʹtitleʹʹ content`` - Creates a new note\n"
                "・``!show_note ʹʹtitleʹʹ`` - Displays a specific note\n"
                "・``!list_notes`` - Shows all saved notes\n"
                "・``!delete_note ʹʹtitleʹʹ`` - Deletes a note\n"
                "・``!subscribe ʹʹtitleʹʹ`` - Subscribe to note updates\n"
                "・``!unsubscribe ʹʹtitleʹʹ`` - Unsubscribe from updates\n"
                "・``!my_subscriptions`` - List notes you're subscribed to"
            ),
            inline=False
        )
        
        embed.add_field(
            name="♪・ Checklist Commands ・♪",
            value=(
                "・``!checklist ʹʹtitleʹʹ item1, item2, item3`` - Creates a checklist\n"
                "・``!show_checklist ʹʹtitleʹʹ`` - Displays a specific checklist\n"
                "・``!list_checklists`` - Shows all saved checklists\n"
                "・``!delete_checklist ʹʹtitleʹʹ`` - Deletes a checklist"
            ),
            inline=False
        )
        
        embed.add_field(
            name="♪・ Auto-Notes Commands ・♪",
            value=(
                "・``!thread_note [thread]`` - Create note from thread messages\n"
                "・``!auto_note [thread]`` - Toggle auto-note for thread\n"
                "・``!conversation_note [minutes]`` - Record channel messages"
            ),
            inline=False
        )
        
        embed.set_footer(text="♪・Bot must have proper permissions in all channels/threads・♪")
        
        await ctx.send(embed=embed)

    @commands.command(name='delete')
    @commands.has_permissions(manage_messages=True)
    async def delete(self, ctx, amount: int):
        """▪ Clear a specified number of messages"""
        if amount < 1:
            await ctx.send("・Please specify a positive number of messages to delete.")
            return
        
        try:
            deleted = await ctx.channel.purge(limit=amount + 1)  # +1 to include command message
            await ctx.send(f"Deleted {len(deleted) - 1} messages.", delete_after=5)
        except discord.Forbidden:
            await ctx.send("❕I don't have permission to delete messages.")
        except discord.HTTPException as e:
            await ctx.send(f"Error deleting messages: {str(e)}")

    def get_channel_info(self, channel_arg: str) -> tuple[int, int, Union[discord.TextChannel, discord.Thread]]:
        """Convert channel mention or ID to channel information"""
        channel_match = re.match(r'<#(\d+)>', channel_arg)
        channel_id = int(channel_match.group(1) if channel_match else channel_arg.strip())
        
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            thread = None
            for guild in self.bot.guilds:
                thread = discord.utils.get(guild.threads, id=channel_id)
                if thread:
                    break
            if thread:
                channel = thread
            
        if not channel or not (isinstance(channel, discord.TextChannel) or isinstance(channel, discord.Thread)):
            raise ValueError(f"♪・Could not find text channel or thread with ID {channel_id}")
            
        return channel.guild.id, channel_id, channel

    @commands.command(name='link')
    @commands.has_permissions(manage_channels=True)
    async def link_channels(self, ctx, channel1: str, channel2: str):
        """🔗 Link two channels/threads for message sharing"""
        try:
            server1_id, chan1_id, channel1_obj = self.get_channel_info(channel1)
            server2_id, chan2_id, channel2_obj = self.get_channel_info(channel2)

            chan1_id = (server1_id, chan1_id)
            chan2_id = (server2_id, chan2_id)

            if chan1_id not in self.linked_channels:
                self.linked_channels[chan1_id] = set()
            if chan2_id not in self.linked_channels:
                self.linked_channels[chan2_id] = set()

            self.linked_channels[chan1_id].add(chan2_id)
            self.linked_channels[chan2_id].add(chan1_id)
            self.save_links()

            await ctx.send(f"🔗 Successfully linked {channel1_obj.mention} and {channel2_obj.mention}!")
        except ValueError as e:
            await ctx.send(f"▪ Error: {str(e)}")
        except Exception as e:
            await ctx.send(f"▪ Error linking channels: {str(e)}")

    @commands.command(name='unlink')
    @commands.has_permissions(manage_channels=True)
    async def unlink_channels(self, ctx, channel1: str, channel2: str):
        """♪・Remove link between two channels/threads"""
        try:
            server1_id, chan1_id, channel1_obj = self.get_channel_info(channel1)
            server2_id, chan2_id, channel2_obj = self.get_channel_info(channel2)

            chan1_id = (server1_id, chan1_id)
            chan2_id = (server2_id, chan2_id)

            if chan1_id in self.linked_channels:
                self.linked_channels[chan1_id].discard(chan2_id)
            if chan2_id in self.linked_channels:
                self.linked_channels[chan2_id].discard(chan1_id)
            self.save_links()

            await ctx.send(f"⏖Successfully unlinked {channel1_obj.mention} and {channel2_obj.mention}!")
        except ValueError as e:
            await ctx.send(f"▪ Error: {str(e)}")
        except Exception as e:
            await ctx.send(f"▪ Error unlinking channels: {str(e)}")

    @commands.command(name='links')
    @commands.has_permissions(manage_channels=True)
    async def list_links(self, ctx):
        """🔗 Show all channel/thread links in the current server"""
        server_id = ctx.guild.id
        server_links = []
        
        for (src_server, src_channel), targets in self.linked_channels.items():
            if src_server == server_id:
                source_channel = self.bot.get_channel(src_channel)
                if source_channel is None:
                    source_channel = discord.utils.get(ctx.guild.threads, id=src_channel)
                
                if source_channel:
                    for target_server, target_channel in targets:
                        target_chan = self.bot.get_channel(target_channel)
                        if target_chan is None:
                            for guild in self.bot.guilds:
                                target_chan = discord.utils.get(guild.threads, id=target_channel)
                                if target_chan:
                                    break
                        
                        if target_chan:
                            server_links.append(f"{source_channel.mention} ↔ {target_chan.mention}")

        if server_links:
            await ctx.send("🔗 Current channel links:\n" + "\n".join(server_links))
        else:
            await ctx.send("🔗 No linked channels in this server.")

    @commands.Cog.listener()
    async def on_message(self, message):
        """⇶Forward messages between linked channels/threads"""
        if message.author.bot:
            return

        channel_id = (message.guild.id, message.channel.id)
        if channel_id in self.linked_channels:
            content = f"🔗 **{message.author.display_name}**: {message.content}"
            files = [await attachment.to_file() for attachment in message.attachments]

            for linked_server, linked_channel in self.linked_channels[channel_id]:
                target_channel = self.bot.get_channel(linked_channel)
                if target_channel is None:
                    for guild in self.bot.guilds:
                        target_channel = discord.utils.get(guild.threads, id=linked_channel)
                        if target_channel:
                            break
                
                if target_channel:
                    try:
                        await target_channel.send(content, files=files)
                    except discord.Forbidden:
                        print(f"♪・Missing permissions for {target_channel.name}")
                    except Exception as e:
                        print(f"♪・Error forwarding message: {e}")

    @commands.Cog.listener()
    async def on_thread_update(self, before, after):
        """Create note when a tracked thread is archived"""
        if before.archived == after.archived or not after.archived:
            return
            
        thread_id = str(after.id)
        note_system = self.bot.get_cog("NoteSystem")
        
        if not note_system or thread_id not in note_system.active_threads:
            return
            
        thread_data = note_system.active_threads[thread_id]
        
        try:
            messages = []
            async for message in after.history(limit=300, oldest_first=True):
                if not message.author.bot:  # Skip bot messages
                    messages.append(message)
            
            if not messages:
                del note_system.active_threads[thread_id]
                return
                
            note_title = f"Archived Thread: {after.name}"
            note_content = f"# Thread Note: {after.name}\n"
            note_content += f"Created: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            note_content += f"Thread started by: {after.owner.name if after.owner else 'Unknown'}\n"
            note_content += f"Thread archived on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            
            for msg in messages:
                timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M")
                note_content += f"**{msg.author.name}** ({timestamp}):\n{msg.content}\n\n"
                
                if msg.attachments:
                    note_content += "**Attachments:**\n"
                    for attachment in msg.attachments:
                        note_content += f"- {attachment.url}\n"
                    note_content += "\n"
                    
            creator = await self.bot.fetch_user(thread_data["creator"])
            creator_name = creator.name if creator else "Unknown"
            
            note_system.notes[note_title] = {
                "content": note_content,
                "created_by": {
                    "user": creator_name,
                    "user_id": thread_data["creator"],
                    "timestamp": datetime.datetime.now().isoformat()
                },
                "thread_id": after.id,
                "subscribers": thread_data["subscribers"]
            }
            note_system.save_notes()
            
            del note_system.active_threads[thread_id]
            
            for user_id in thread_data["subscribers"]:
                try:
                    user = await self.bot.fetch_user(int(user_id))
                    if user:
                        view = NoteView(note_title, note_content, thread_data["subscribers"])
                        view.subscribe_button.label = "🔕 Unsubscribe"
                        view.subscribe_button.style = discord.ButtonStyle.danger
                        
                        await user.send(f"📝 Note created from archived thread: **{note_title}** (click to view)", view=view)
                except Exception as e:
                    print(f"Failed to notify user {user_id} about archived thread note: {e}")
        
        except Exception as e:
            print(f"Error creating note for archived thread {after.name}: {e}")
            if thread_id in note_system.active_threads:
                del note_system.active_threads[thread_id]

@bot.event
async def on_ready():
    print(f' Xo Marcus activated.')
    try:
        await bot.add_cog(NoteSystem(bot))
        await bot.add_cog(ChannelManager(bot))
        print("All features loaded.")
    except Exception as e:
        print(f"Error loading features: {e}")

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors"""
    if isinstance(error, commands.CommandNotFound):
        return
    raise error
    
bot.run('YOUR_TOKEN_HERE')
