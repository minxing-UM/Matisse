import threading
import time

if __package__:
    from .chat_manager import ChatManager
    from .generation_queue import GenerationQueue
    from .thought_manager import ThoughtManager
    from .emotion_manager import EmotionManager
    from .life_manager import LifeManager
    from .memory_manager import MemoryManager
    from .ollama_client import PERSONALITY_FILE, ask_matisse, load_settings, private_completion, summarize_memories
    from .personality_manager import startup_personality
    from .trait_manager import TraitManager
    from .web_manager import WebManager
else:
    from chat_manager import ChatManager
    from generation_queue import GenerationQueue
    from thought_manager import ThoughtManager
    from emotion_manager import EmotionManager
    from life_manager import LifeManager
    from memory_manager import MemoryManager
    from ollama_client import PERSONALITY_FILE, ask_matisse, load_settings, private_completion, summarize_memories
    from personality_manager import startup_personality
    from trait_manager import TraitManager
    from web_manager import WebManager


def get_model_name() -> str:
    return load_settings()["model"]


def create_new_chat():

    model = get_model_name()

    chat = ChatManager(
        model=model
    )

    print()
    print("=" * 50)
    print("Matisse v0.0.3")
    print("=" * 50)
    print()

    print(
        f"Model : {model}"
    )

    print(
        f"Chat  : {chat.chat_id}"
    )

    print()

    print("Commands:")
    print("  /new   Start a new chat")
    print("  /path  Show chat JSON path")
    print("  /mood  Show internal emotion state")
    print("  /refresh  Read configured web sources")
    print("  /exit  Exit Matisse")

    print()

    return chat


def print_startup_debug(
    report
):

    print()
    print(
        "[Affective System]"
    )

    print(
        "Elapsed since last interaction:"
        f" {report['elapsed_hours']} hours"
    )

    print(
        "Circadian state:"
        f" {report['circadian']['label']}"
    )

    print(
        "Energy:"
        f" {report['circadian']['energy']}"
    )

    print()


def print_mood(emotion_manager):
    state = emotion_manager.get_state()
    print()
    print("[Matisse Internal State]")
    for name, value in state.items():
        print(f"{name:12}: {value:5.1f}")
    print()


def run_idle_cycle(life_manager, emotion_manager, web_manager, thought_callback=None):
    """Maintain idle state, then let the scheduled model task decide if due."""
    activity = life_manager.catch_up()
    if activity:
        emotion_manager.apply_idle_effect(activity["elapsed_hours"])
        if life_manager.web_due(6):
            # Titles are enough for a lightweight presence cue; no model summary is needed.
            for item in web_manager.refresh()[:3]:
                title = (item.get("title") or "").strip()
                if title:
                    web_manager.store(item, title)
            life_manager.mark_web_refresh()

    if thought_callback:
        return thought_callback()


def start_idle_worker(
    life_manager,
    emotion_manager,
    web_manager,
    generation_lock=None,
    deliver_to_console=True,
    thought_callback=None
):
    generation_lock = generation_lock or GenerationQueue()
    def worker():
        while True:
            try:
                with generation_lock.background() as admitted:
                    if admitted:
                        message = run_idle_cycle(
                            life_manager, emotion_manager, web_manager, thought_callback
                        )
                        if deliver_to_console and message:
                            print(f"\nMatisse: {message}\nYou: ", end="", flush=True)
            except Exception as error:
                print(f"[Idle worker] {type(error).__name__}: {error}")
            time.sleep(life_manager.decision_interval_seconds)
    threading.Thread(target=worker, daemon=True, name="matisse-idle").start()


def main():

    settings = load_settings()
    startup_personality(PERSONALITY_FILE)

    memory_manager = MemoryManager(
        summary_interval=settings.get("memory_summary_interval", 6),
        context_limit=settings.get("memory_context_limit", 8),
        fatigue_recall_threshold=settings.get("fatigue_memory_recall_threshold", 60),
        fatigue_recall_chance=settings.get("fatigue_memory_recall_chance", 0.25),
        fatigue_recall_limit=settings.get("fatigue_memory_recall_limit", 2),
        fatigue_recall_importance_ceiling=settings.get(
            "fatigue_memory_recall_importance_ceiling", 2.5
        ),
        embedding_enabled=settings.get("memory_embedding_enabled", True),
        embedding_model=settings.get("memory_embedding_model", "bge-m3:latest"),
        embedding_top_k=settings.get("memory_embedding_top_k", 5),
        embedding_min_similarity=settings.get(
            "memory_embedding_min_similarity", 0.48
        )
    )
    web_manager = WebManager()
    life_manager = LifeManager()

    emotion_manager = (
        EmotionManager()
    )

    startup_report = (
        emotion_manager
        .update_on_startup()
    )


    print_startup_debug(
        startup_report
    )

    chat = create_new_chat()
    generation_lock = GenerationQueue()
    thoughts = ThoughtManager()
    active_chat = {"id": chat.chat_id}

    def generate_thought():
        return thoughts.generate(
            ChatManager.load(active_chat["id"]), life_manager, emotion_manager, memory_manager
        )

    start_idle_worker(
        life_manager, emotion_manager, web_manager,
        generation_lock=generation_lock, thought_callback=generate_thought
    )

    pending_message = life_manager.take_pending()
    if pending_message:
        print(f"Matisse left you a message: {pending_message}\n")

    while True:

        try:

            user_input = input(
                "You: "
            ).strip()

        except (
            KeyboardInterrupt,
            EOFError
        ):

            print()
            print(
                "Matisse closed."
            )

            break

        if not user_input:

            continue

        with generation_lock:
            chat = ChatManager.load(active_chat["id"])
            life_manager.mark_user_return()
            continuity_context = life_manager.continuity_context()
            life_manager.note_user_topic(user_input)

            command = (
                user_input.lower()
            )

            # =================================================
            # Commands
            # =================================================

            if command == "/exit":

                print()
                print(
                    "Matisse closed."
                )

                break

            if command == "/new":

                chat = create_new_chat()
                active_chat["id"] = chat.chat_id

                continue

            if command == "/path":

                print()

                print(
                    f"Chat file: "
                    f"{chat.file_path}"
                )

                print()

                continue

            if command == "/mood":

                print_mood(
                    emotion_manager
                )

                continue

            if command == "/refresh":
                saved = 0
                for item in web_manager.refresh()[:5]:
                    try:
                        summary = private_completion(
                            "Summarize this web item in concise Chinese. Preserve uncertainty and do not invent details.",
                            f"Title: {item['title']}\nSource: {item['source']}\nText: {item['text']}"
                        )
                        if summary:
                            web_manager.store(item, summary)
                            saved += 1
                    except Exception:
                        continue
                print(f"Web refresh complete: {saved} new item(s) saved.\n")
                continue

            # =================================================
            # User message
            # =================================================

            chat.add_message(
                role="user",
                content=user_input
            )

            # =================================================
            # Build current internal state
            # =================================================

            runtime_context = (
                emotion_manager
                .build_runtime_context()
            )
            runtime_context += "\n\n" + life_manager.goal_context()
            if continuity_context:
                runtime_context += "\n\n" + continuity_context

            current_settings = load_settings()
            memory_manager.summary_interval = current_settings.get(
                "memory_summary_interval", 6
            )
            if current_settings.get("memory_enabled", True):
                memory_context = memory_manager.build_runtime_context(
                    user_input,
                    tiredness=emotion_manager.get_state()["tiredness"]
                )
                if memory_context:
                    runtime_context += "\n\n" + memory_context

            web_context = web_manager.build_runtime_context(user_input)
            if web_context:
                runtime_context += "\n\n" + web_context

            print()
            print(
                "Matisse is thinking..."
            )
            print()

            # =================================================
            # Generate reply + hidden emotional reaction
            # =================================================

            try:

                turn = ask_matisse(
                    chat.get_messages_for_model(),
                    runtime_context=runtime_context
                )

            except Exception as error:

                print(
                    "Ollama / structured output error:"
                )

                print(error)

                print()

                continue

            # =================================================
            # Apply emotional change
            # =================================================

            proposed_delta = (
                turn
                .emotion_delta
                .model_dump()
            )

            emotion_report = emotion_manager.apply_turn_emotions(
                proposed_delta, turn.user_affect.model_dump(), user_input
            )

            emotion_manager.mark_interaction()

            mood_after = (
                emotion_manager
                .get_state()
            )

            # =================================================
            # Save visible reply + hidden metadata
            # =================================================

            chat.add_message(
                role="assistant",

                content=turn.reply,

                metadata={
                    "mood_label":
                        turn.mood_label,

                    "emotion_delta_proposed":
                        proposed_delta,

                    **emotion_report,

                    "mood_after":
                        mood_after
                }
            )

            # =================================================
            # User only sees the actual reply
            # =================================================

            print(
                f"Matisse: {turn.reply}"
            )

            print()

            # This runs after the visible reply using an independent model call,
            # so the memory work remains outside the user-facing conversation.
            memory_manager.queue_turn(
                chat.chat_id,
                user_input,
                turn.reply,
                user_message_id=chat.messages[-2]["id"],
                assistant_message_id=chat.messages[-1]["id"]
            )

            if (
                current_settings.get("memory_summary_mode", "automatic") == "automatic"
                and memory_manager.should_summarize()
            ):
                try:
                    memory_manager.summarize_pending(summarize_memories)
                except Exception as error:
                    # Keep pending turns for a later hidden retry; do not disrupt
                    # an otherwise successful user conversation.
                    print(f"[Memory summary] {type(error).__name__}; queued turns retained.")


if __name__ == "__main__":
    main()
