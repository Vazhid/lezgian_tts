import os
import logging
import numpy as np
from typing import Optional, Dict, Union
from transformers import pipeline
import scipy.io.wavfile
import soundfile as sf

class LezgianTTS:
    def __init__(self, model_id: str = "model", use_gpu: bool = False, logger: Optional[logging.Logger] = None):
        """
        Инициализация синтезатора речи
        
        Args:
            model_id (str): Путь к модели или идентификатор в HuggingFace Hub
            use_gpu (bool): Использовать ли GPU для вычислений
            logger (Logger): Логгер для записи событий (если None, будет создан новый)
        """
        self._setup_logger(logger)
        self.model_id = model_id
        self.use_gpu = use_gpu
        self.synthesiser = None
        self._initialize_model()

    def _setup_logger(self, logger: Optional[logging.Logger]) -> None:
        """Настройка логгера"""
        self.logger = logger or logging.getLogger(__name__)
        if not logger:
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )

    def _initialize_model(self) -> None:
        """Загрузка и инициализация модели TTS"""
        try:
            device = "cuda:0" if self.use_gpu else "cpu"
            self.logger.info(f"Загрузка модели TTS (устройство: {device})...")
            
            os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
            if not self.use_gpu:
                os.environ['CUDA_VISIBLE_DEVICES'] = '-1'

            self.synthesiser = pipeline(
                "text-to-speech",
                model=self.model_id,
                device=device,
                trust_remote_code=True
            )
            
            self.logger.info(f"Модель {self.model_id} успешно загружена")
            
        except Exception as e:
            self.logger.error(f"Ошибка при загрузке модели: {str(e)}", exc_info=True)
            raise RuntimeError(f"Не удалось загрузить модель: {str(e)}")

    def synthesize(self, text: str, **kwargs) -> Optional[Dict]:
        """
        Синтезирует речь из текста
        
        Args:
            text (str): Текст для синтеза
            **kwargs: Дополнительные параметры для модели
            
        Returns:
            Optional[Dict]: Словарь с аудио данными и частотой дискретизации или None при ошибке
        """
        if not self.synthesiser:
            self.logger.error("Модель не инициализирована")
            return None

        try:
            self.logger.info(f"Синтез речи для текста: '{text[:50]}...'")
            
            normalized_text = self._normalize_text(text)
            
            speech = self.synthesiser(normalized_text, **kwargs)
            
            if not self._validate_audio_output(speech):
                return None
                
            return speech
            
        except Exception as e:
            self.logger.error(f"Ошибка синтеза речи: {str(e)}", exc_info=True)
            return None

    def save_to_file(self, text: str, output_path: str, format: str = 'wav', **kwargs) -> bool:
        """
        Синтезирует речь и сохраняет её в файл
        
        Args:
            text (str): Текст для синтеза
            output_path (str): Путь для сохранения файла
            format (str): Формат файла ('wav', 'mp3', 'ogg')
            **kwargs: Дополнительные параметры для модели
            
        Returns:
            bool: True если сохранение прошло успешно, False при ошибке
        """
        try:
            speech = self.synthesize(text, **kwargs)
            if speech is None:
                return False

            audio_data = speech["audio"]
            sr = speech["sampling_rate"]
            
            audio_data = self._prepare_audio_data(audio_data)
            
            if format.lower() == 'wav':
                scipy.io.wavfile.write(output_path, sr, audio_data)
            else:
                sf.write(output_path, audio_data, sr, format=format.lower())
            
            self.logger.info(f"Аудио успешно сохранено в {output_path} (формат: {format})")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка при сохранении аудио: {str(e)}", exc_info=True)
            return False

    def _normalize_text(self, text: str) -> str:
        """Нормализация входного текста"""
        # TODO: Добавить специфичную для лезгинского языка нормализацию
        return text.strip()

    def _validate_audio_output(self, speech: Dict) -> bool:
        """Проверка корректности выходных данных модели"""
        if not isinstance(speech, dict):
            self.logger.error("Модель вернула некорректный тип данных")
            return False
            
        if "audio" not in speech or "sampling_rate" not in speech:
            self.logger.error("Модель вернула данные без обязательных полей")
            return False
            
        if len(speech["audio"]) == 0:
            self.logger.error("Модель вернула пустые аудио данные")
            return False
            
        return True

    def _prepare_audio_data(self, audio_data: Union[np.ndarray, list]) -> np.ndarray:
        """Подготовка аудио данных к сохранению"""
        if isinstance(audio_data, list):
            audio_data = audio_data[0]
            
        audio_data = np.squeeze(audio_data)
        
        if audio_data.dtype == np.float32:
            audio_data = np.int16(audio_data * 32767)
            
        return audio_data

    def get_model_info(self) -> Dict:
        """Получение информации о загруженной модели"""
        if not self.synthesiser:
            return {"status": "Модель не загружена"}
            
        return {
            "model_id": self.model_id,
            "device": "GPU" if self.use_gpu else "CPU",
            "sampling_rate": self.synthesiser.model.config.sampling_rate if hasattr(self.synthesiser.model, 'config') else "unknown"
        }