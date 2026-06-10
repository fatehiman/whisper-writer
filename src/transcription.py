import io
import os
import sys
import ctypes
import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel
from openai import OpenAI

from utils import ConfigManager

# Map a Windows primary-language id (low 10 bits of the LANGID) to a Whisper
# language code. Extend as needed; unmapped layouts fall back to auto-detect.
_PRIMARY_LANG_TO_WHISPER = {
    0x09: 'en',  # English
    0x29: 'fa',  # Persian (Farsi)
    0x1f: 'tr',  # Turkish
    0x01: 'ar',  # Arabic
    0x07: 'de',  # German
    0x0c: 'fr',  # French
    0x19: 'ru',  # Russian
    0x0a: 'es',  # Spanish
}


def get_active_keyboard_language():
    """Return the Whisper language code for the active window's keyboard layout.

    Mirrors Windows voice-typing behaviour: the dictation language follows the
    selected input language. Returns None on non-Windows or unknown layouts.
    """
    if sys.platform != 'win32':
        return None
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        user32.GetKeyboardLayout.restype = ctypes.c_void_p

        hwnd = user32.GetForegroundWindow()
        thread_id = user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), 0)
        hkl = user32.GetKeyboardLayout(thread_id) or 0
        primary = (hkl & 0xFFFF) & 0x3FF  # LANGID -> primary language id
        return _PRIMARY_LANG_TO_WHISPER.get(primary)
    except Exception:
        return None


def resolve_language():
    """Pick the transcription language. If config 'language' is set, honour it;
    otherwise follow the active keyboard layout (falling back to auto-detect)."""
    configured = ConfigManager.get_config_section('model_options')['common']['language']
    if configured:
        return configured
    kb_lang = get_active_keyboard_language()
    if kb_lang:
        ConfigManager.console_print(f'Language from keyboard layout: {kb_lang}')
    return kb_lang  # None -> Whisper auto-detects

def create_local_model():
    """
    Create a local model using the faster-whisper library.
    """
    ConfigManager.console_print('Creating local model...')
    local_model_options = ConfigManager.get_config_section('model_options')['local']
    compute_type = local_model_options['compute_type']
    model_path = local_model_options.get('model_path')

    if compute_type == 'int8':
        device = 'cpu'
        ConfigManager.console_print('Using int8 quantization, forcing CPU usage.')
    else:
        device = local_model_options['device']

    try:
        if model_path:
            ConfigManager.console_print(f'Loading model from: {model_path}')
            model = WhisperModel(model_path,
                                 device=device,
                                 compute_type=compute_type,
                                 download_root=None)  # Prevent automatic download
        else:
            model = WhisperModel(local_model_options['model'],
                                 device=device,
                                 compute_type=compute_type)
    except Exception as e:
        ConfigManager.console_print(f'Error initializing WhisperModel: {e}')
        ConfigManager.console_print('Falling back to CPU.')
        model = WhisperModel(model_path or local_model_options['model'],
                             device='cpu',
                             compute_type=compute_type,
                             download_root=None if model_path else None)

    ConfigManager.console_print('Local model created.')
    return model

def transcribe_local(audio_data, local_model=None):
    """
    Transcribe an audio file using a local model.
    """
    if not local_model:
        local_model = create_local_model()
    model_options = ConfigManager.get_config_section('model_options')

    # Convert int16 to float32
    audio_data_float = audio_data.astype(np.float32) / 32768.0

    response = local_model.transcribe(audio=audio_data_float,
                                      language=resolve_language(),
                                      initial_prompt=model_options['common']['initial_prompt'],
                                      condition_on_previous_text=model_options['local']['condition_on_previous_text'],
                                      temperature=model_options['common']['temperature'],
                                      vad_filter=model_options['local']['vad_filter'],)
    return ''.join([segment.text for segment in list(response[0])])

def transcribe_api(audio_data):
    """
    Transcribe an audio file using the OpenAI API.
    """
    model_options = ConfigManager.get_config_section('model_options')
    client = OpenAI(
        api_key=os.getenv('OPENAI_API_KEY') or None,
        base_url=model_options['api']['base_url'] or 'https://api.openai.com/v1'
    )

    # Convert numpy array to WAV file
    byte_io = io.BytesIO()
    sample_rate = ConfigManager.get_config_section('recording_options').get('sample_rate') or 16000
    sf.write(byte_io, audio_data, sample_rate, format='wav')
    byte_io.seek(0)

    response = client.audio.transcriptions.create(
        model=model_options['api']['model'],
        file=('audio.wav', byte_io, 'audio/wav'),
        language=resolve_language(),
        prompt=model_options['common']['initial_prompt'],
        temperature=model_options['common']['temperature'],
    )
    return response.text

def post_process_transcription(transcription):
    """
    Apply post-processing to the transcription.
    """
    transcription = transcription.strip()
    post_processing = ConfigManager.get_config_section('post_processing')
    if post_processing['remove_trailing_period'] and transcription.endswith('.'):
        transcription = transcription[:-1]
    if post_processing['add_trailing_space']:
        transcription += ' '
    if post_processing['remove_capitalization']:
        transcription = transcription.lower()

    return transcription

def transcribe(audio_data, local_model=None):
    """
    Transcribe audio date using the OpenAI API or a local model, depending on config.
    """
    if audio_data is None:
        return ''

    if ConfigManager.get_config_value('model_options', 'use_api'):
        transcription = transcribe_api(audio_data)
    else:
        transcription = transcribe_local(audio_data, local_model)

    return post_process_transcription(transcription)

