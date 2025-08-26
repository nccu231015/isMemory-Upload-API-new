document.addEventListener('DOMContentLoaded', function() {
    const submitBtn = document.getElementById('submit-btn');
    const videoUrlInput = document.getElementById('video-url');
    const loadingSection = document.getElementById('loading');
    const resultsSection = document.getElementById('results');
    
    submitBtn.addEventListener('click', analyzeVideo);
    
    async function analyzeVideo() {
        const url = videoUrlInput.value.trim();
        console.log(`前端獲取的URL: '${url}' (長度: ${url.length})`);
        
        if (!url) {
            alert('請輸入有效的影片連結');
            return;
        }
        
        const source = document.querySelector('input[name="platform"]:checked').value;
        const storeInDb = document.getElementById('store-in-db').checked;
        
        console.log(`準備發送請求: url='${url}', source='${source}', storeInDb=${storeInDb}`);
        
        // 顯示載入中
        loadingSection.classList.remove('hidden');
        resultsSection.classList.add('hidden');
        submitBtn.disabled = true;
        
        try {
            const formData = new FormData();
            formData.append('url', url);
            formData.append('source', source);
            formData.append('store_in_db', storeInDb);
            
            const response = await fetch('/api/process', {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '處理請求時發生錯誤');
            }
            
            const data = await response.json();
            displayResults(data.analysis);
            
        } catch (error) {
            alert('錯誤: ' + error.message);
        } finally {
            loadingSection.classList.add('hidden');
            submitBtn.disabled = false;
        }
    }
    
    function displayResults(analysis) {
        // 顯示結果區塊
        resultsSection.classList.remove('hidden');
        
        // 填充資料
        document.getElementById('summary').textContent = analysis.summary;
        document.getElementById('important-time').textContent = analysis.important_time || '無';
        document.getElementById('important-location').textContent = analysis.important_location || '無';
        document.getElementById('ocr-text').textContent = analysis.ocr_text || '無文字內容';
        document.getElementById('caption').textContent = analysis.caption || '無字幕內容';
        
        // 設置原始連結
        const originalLink = document.getElementById('original-link');
        originalLink.href = analysis.original_path;
    }
});